"""VOL-03 fuzzy deduplication pipeline for legacy voluntarios (issue #36).

The pipeline deduplicates free-text references to voluntarios that the
legacy Access backend stores across multiple tables
(``TbVoluntariosParaAutorrellenables``, ``TbEntradas``, ``TbAdopcion``,
``TbAcogidaAnimal``, ``TbTerapias``) without any FK relationship.

**Contract** (cross-ref issue #36 + ``docs/legacy-volunteer-roles.md``):

- Input: a list of :class:`VolunteerRef` (name + source provenance +
  optional DNI).
- Output: a list of :class:`MergedCluster`, each carrying the canonical
  name, the resolved DNI (or ``None``), the source refs that landed
  in the cluster, the merge decision, the reason, and a confidence
  score.
- Algorithm:

  1. **Exact-name pre-pass** — refs whose ``name`` strings normalise
     to the same value (lower-case + whitespace-stripped) are
     unioned. Same-row canonicalisation.
  2. **DNI pre-pass** — refs with the same non-empty ``dni`` are
     unioned (secondary key). This overrides the name-based union
     and catches the married-name / typo / free-text drift that
     the fuzzy stage cannot reach.
  3. **Fuzzy union** — every ``(i, j)`` pair in the input is scored
     under ``rapidfuzz.fuzz.WRatio`` after pre-normalising via
     :func:`_strip_accents` + :func:`_normalise_name` (diacritic
     stripping + lower-case + whitespace collapse). Pairs whose
     score is ``>= fuzzy_threshold`` (default 85) are unioned.
     The exhaustive ``O(n^2)`` scoring is intentional at the
     legacy dataset scale (a few thousand refs total across
     ``TbVoluntariosParaAutorrellenables``, ``TbEntradas``,
     ``TbAdopcion``, ``TbAcogidaAnimal``, ``TbTerapias``);
     ``rapidfuzz``'s C++ implementation finishes in well under
     a second at that scale. If the input ever grows past the
     low thousands the caller should switch to a blocking stage
     upstream of this function (e.g. group refs by first-letter
     of the normalised name) — that is a deliberate future
     optimisation, not a current one.
  4. **DNI conflict split** — a cluster that contains two refs with
     different non-empty DNIs is BROKEN: every ref becomes its own
     cluster flagged ``needs_review`` with reason
     ``"ambiguous_dni_collision"``. The operator must resolve the
     conflict via the manual review interface.
  5. **DNI consensus** — when a cluster has exactly one non-empty DNI
     (with all other refs in the cluster carrying either the same DNI
     or no DNI), the cluster's ``dni`` is that value.
  6. **Decision tag** — ``"auto_merged"`` (>=2 sources OR
     cross-cluster merge via fuzzy/DNI), ``"unique"`` (single source,
     no merge candidate).

**Idempotence**: the function is referentially transparent on its
input. Two runs with the same ``VolunteerRef`` list produce
byte-identical output (verified by ``tests/migration/test_volunteer_dedup.py::
test_dedup_is_idempotent_double_run``). The reason: the algorithm is
deterministic union-find over the input order, no timestamps, no
random tie-breaking.

**PII contract**: any logging that mentions a volunteer's data goes
through :func:`app.core.logging.log_safe` so the closed
``REDACTED_FIELDS`` (``dni``, ``tel1``, ``tel2``, ``email``, …) are
scrubbed. The atom
``tests/migration/test_volunteer_dedup.py::test_dedup_does_not_emit_raw_dni_in_logs``
asserts the invariant via ``caplog``.

**Module size budget** (AGENTS.md rule 21): the implementation stays
under the 700-line cap. The CLI bridge is a separate module
(``migration.cli_volunteer_dedup``) so this file stays focused on the
pure algorithm.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from rapidfuzz import fuzz

# log_safe lives in ``app.core.logging`` — importing it here means the
# dedup module pulls in the FastAPI app's logging path. The dedup is a
# CLI-side helper, not a web-side route handler, so the APAP003 ban on
# ``logger.*`` chains in ``app/`` does NOT apply (the rule scopes the
# ban to ``app/``; this module lives in ``migration/``). We still go
# through ``log_safe`` for the redaction invariant — that is the point
# of routing every log through a single wrapper.
from app.core.logging import log_safe

# Closed list of merge decisions exposed to the CLI / operator.
# ``Literal`` keeps mypy honest; adding a new decision here forces a
# docstring + test update.
Decision = Literal["auto_merged", "needs_review", "unique"]

# Reasons are descriptive tags (not free text) so the operator can
# grep the manual-review output by reason and the closed-list policy
# in ``scripts/check_rules.py`` style applies.
Reason = Literal[
    "exact_name_match",
    "dni_exact_match",
    "fuzzy_name_match",
    "ambiguous_dni_collision",
    "unique",
]

# Default fuzzy threshold (0..100 scale used by rapidfuzz). The
# weighted ratio is diacritic-insensitive and case-insensitive; 85
# collapses "María García" / "Maria Garcia" (WRatio ~83) under the
# DNI override path while keeping "Jon Smith" / "John Smith" out of
# each other's clusters without an explicit DNI tie. Operators can
# override this in :func:`dedup_volunteers` when the dataset shows
# that the default is too aggressive or too conservative.
DEFAULT_FUZZY_THRESHOLD: Final[int] = 85


@dataclass(frozen=True, slots=True)
class VolunteerRef:
    """One free-text reference to a voluntario in a legacy table.

    ``source_table`` is the legacy table name (e.g. ``"TbEntradas"``)
    and ``source_row_id`` is a stable identifier of the row inside
    that table (typically the legacy primary key — the column is
    table-dependent). The pair is what the manual-review UI surfaces
    to the operator so they can navigate back to the legacy row and
    confirm or override the merge.

    ``dni`` is the optional secondary dedup key. Legacy
    ``TbVoluntariosParaAutorrellenables`` has no DNI column
    (Dysflow-verified 2026-07-11); only the web side carries it.
    The dedup therefore relies on the operator having pre-populated
    ``dni`` from a parallel source (e.g. a web-side manual entry
    exported for the offline dedup run) or accepts the
    name-only / fuzzy-only path when ``dni`` is ``None`` everywhere.
    """

    name: str
    source_table: str
    source_row_id: str
    dni: str | None = None

    def __post_init__(self) -> None:
        # Refuse an empty name string at construction time so the
        # rest of the algorithm does not need to special-case
        # ``""`` (and so the CLI cannot accidentally pass an empty
        # ref that would falsely match every other empty ref).
        if not self.name or not self.name.strip():
            raise ValueError("VolunteerRef.name must be a non-empty string")
        if not self.source_table or not self.source_table.strip():
            raise ValueError("VolunteerRef.source_table must be a non-empty string")
        if not self.source_row_id or not self.source_row_id.strip():
            raise ValueError("VolunteerRef.source_row_id must be a non-empty string")
        if self.dni is not None and not self.dni.strip():
            # Treat empty string the same as missing — the source
            # schema sometimes uses ``""`` to mean "no DNI".
            object.__setattr__(self, "dni", None)


@dataclass(frozen=True, slots=True)
class MergedCluster:
    """Result of grouping :class:`VolunteerRef` rows that the pipeline
    identified as the same person.

    Attributes:
        canonical_name: representative name (the first ref in the
            cluster's input order).
        dni: resolved DNI (``None`` if the cluster has no DNI). When
            the cluster contains two refs with different DNIs the
            cluster is BROKEN at this layer; the ``decision`` and
            ``reason`` carry the ``needs_review`` tag instead.
        sources: the refs that landed in this cluster (in input
            order).
        decision: one of :data:`Decision`.
        reason: one of :data:`Reason`. ``"unique"`` only appears with
            ``decision == "unique"``; the auto-merged reasons are
            the three merge heuristics.
        confidence: best similarity score (0..100) that triggered
            the merge; ``None`` for ``unique`` clusters.
    """

    canonical_name: str
    dni: str | None
    sources: list[VolunteerRef]
    decision: Decision
    reason: Reason
    confidence: float | None = field(default=None)

    def __post_init__(self) -> None:
        # Cross-field invariants the rest of the code depends on.
        if not self.sources:
            raise ValueError("MergedCluster.sources must contain at least one ref")
        if self.decision == "unique" and len(self.sources) != 1:
            raise ValueError(
                f"decision='unique' requires exactly one source; got {len(self.sources)}"
            )
        if self.decision == "auto_merged" and len(self.sources) < 2:
            raise ValueError(
                f"decision='auto_merged' requires >=2 sources; got {len(self.sources)}"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 100.0:
            raise ValueError(
                f"confidence must be in [0, 100]; got {self.confidence!r}"
            )


def _normalise_name(name: str) -> str:
    """Lower-case + strip + collapse whitespace.

    Used for the exact-name pre-pass so that "Maria Garcia " and
    " maria garcia" are recognised as identical without relying on
    the fuzzy stage. ``rapidfuzz`` handles diacritics; this helper
    handles the cheap case.
    """
    return " ".join(name.strip().lower().split())


def _strip_accents(name: str) -> str:
    """Decompose to NFD then drop combining marks.

    The fuzzy stage needs this because ``rapidfuzz.fuzz.WRatio``
    treats accent-stripped variants ("Maria" / "María") as a
    partial mismatch that drops the score below the threshold.
    Decomposing + dropping the combining marks gives a plain
    ASCII string that ``WRatio`` can match at 100% — which is
    what the legacy free-text actually wants ("María García" in
    one row, "Maria Garcia" in another row are the same person).
    """
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(ch)
    )


def _cluster_by_exact_name(
    refs: Sequence[VolunteerRef],
) -> dict[str, list[int]]:
    """Group ref indices by their normalised name.

    Returns ``{normalised_name: [index_in_refs, ...]}``. Refs that
    end up in the same bucket are forced into the same cluster.
    """
    buckets: dict[str, list[int]] = {}
    for idx, ref in enumerate(refs):
        buckets.setdefault(_normalise_name(ref.name), []).append(idx)
    return buckets


def _cluster_by_dni(
    refs: Sequence[VolunteerRef],
) -> dict[str, list[int]]:
    """Group ref indices by their non-empty DNI string.

    Mirrors :func:`_cluster_by_exact_name`. Refs sharing a DNI
    collapse even when their names differ — this is the secondary
    key path that overrides the name-based pre-pass.
    """
    buckets: dict[str, list[int]] = {}
    for idx, ref in enumerate(refs):
        if ref.dni is None:
            continue
        buckets.setdefault(ref.dni, []).append(idx)
    return buckets


class _UnionFind:
    """Union-find with deterministic, in-order merge.

    Wrapping the dict + path compression in a class makes the
    ``dedup_volunteers`` body linear and readable. The data
    structure is intentionally tiny: ``parent`` maps ``index ->
    parent index`` and ``find`` walks up to the root with path
    compression on the way back.
    """

    __slots__ = ("parent", "_size")

    def __init__(self, n: int) -> None:
        self.parent: list[int] = list(range(n))
        self._size: int = n

    def find(self, x: int) -> int:
        parent = self.parent
        root = x
        while parent[root] != root:
            root = parent[root]
        # Path compression: flatten the chain.
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # Always union the larger index into the smaller — keeps the
        # root deterministic and stable across runs (root choice
        # drives the canonical_name / source order in the output,
        # so this is what makes the function idempotent).
        if rx < ry:
            self.parent[ry] = rx
        else:
            self.parent[rx] = ry


def _fuzzy_candidate_pairs(
    refs: Sequence[VolunteerRef],
    *,
    threshold: int,
) -> Iterable[tuple[int, int]]:
    """Yield ``(i, j)`` index pairs whose name similarity >= ``threshold``.

    The function scores every ``(i, j)`` pair in the input (the
    legacy dataset is at most a few thousand refs; ``rapidfuzz``
    is C++ so even ``O(n^2)`` runs in well under a second at this
    scale). We could use blocking (e.g. by first letter) but the
    operator's review step is the safety net for the edge cases
    blocking would miss; the simpler exhaustive score is what
    makes the algorithm auditable and idempotent.

    ``WRatio`` is diacritic- and case-insensitive so "María García"
    and "Maria Garcia" score high enough to join — but only when
    the strings are first normalised through :func:`_strip_accents`
    + :func:`_normalise_name`. Without the accent strip, the score
    for "María García" / "Maria Garcia" is 83 (below the 85
    threshold), which would miss the legacy-accent-drift case
    that motivates the fuzzy stage.
    """
    normalised = [_strip_accents(_normalise_name(ref.name)) for ref in refs]
    n = len(refs)
    for i in range(n):
        for j in range(i + 1, n):
            score = fuzz.WRatio(normalised[i], normalised[j])
            if score >= threshold:
                yield i, j


def _build_clusters(
    refs: Sequence[VolunteerRef],
    uf: _UnionFind,
    *,
    _threshold: int,
) -> list[list[int]]:
    """Materialise the union-find into ``{root: [index, ...]}`` buckets.

    The output preserves input order within each bucket and sorts
    the buckets by their smallest index — so the first cluster
    contains the earliest ref in the input. That order is part of
    the idempotence contract (the canonical_name of each cluster is
    the name of its first ref in input order).
    """
    groups: dict[int, list[int]] = {}
    for idx in range(len(refs)):
        groups.setdefault(uf.find(idx), []).append(idx)
    # Sort by the smallest index in each group — deterministic.
    return [sorted(indices, key=lambda i: i) for _, indices in
            sorted(groups.items(), key=lambda kv: min(kv[1]))]


def _resolve_dni(group: list[int], refs: Sequence[VolunteerRef]) -> tuple[str | None, bool]:
    """Resolve the cluster's DNI and detect ambiguity.

    Returns ``(resolved_dni, is_ambiguous)``. The ambiguity flag
    is ``True`` when two refs in the same group carry different
    non-empty DNIs — the only condition that triggers the
    ``needs_review`` decision with reason ``ambiguous_dni_collision``.

    Rules:

    - 0 non-empty DNIs -> resolved_dni=None, not ambiguous.
    - 1 non-empty DNI (rest empty/None) -> resolved_dni=that DNI, not ambiguous.
    - All same non-empty DNI -> resolved_dni=that DNI, not ambiguous.
    - Two different non-empty DNIs -> resolved_dni=None, ambiguous=True.
    """
    dnis = {refs[i].dni for i in group if refs[i].dni is not None}
    if len(dnis) <= 1:
        # 0 or 1 unique non-empty DNIs: unambiguous.
        return (next(iter(dnis), None), False)
    # >=2 unique non-empty DNIs in the same group.
    return (None, True)


def _cluster_decision(
    group: list[int],
    refs: Sequence[VolunteerRef],
    *,
    _threshold: int,
) -> tuple[Decision, Reason, float | None]:
    """Classify a cluster as ``auto_merged`` / ``needs_review`` / ``unique``.

    The classification is based on (a) the size of the group,
    (b) whether the pre-passes already unioned these refs, and
    (c) the highest WRatio score between any two refs in the group
    (used as the confidence value for the operator UI).
    """
    if len(group) == 1:
        return ("unique", "unique", None)

    # Best pairwise WRatio across the group — the operator's UI
    # surfaces this so they can decide whether to trust the merge.
    # Same accent-stripped pre-normalisation as the candidate-pair
    # stage so the score reflects the diacritic-insensitive view.
    best_score = 0.0
    for i_pos, i in enumerate(group):
        for j in group[i_pos + 1 :]:
            score = fuzz.WRatio(
                _strip_accents(_normalise_name(refs[i].name)),
                _strip_accents(_normalise_name(refs[j].name)),
            )
            if score > best_score:
                best_score = score

# Determine which heuristic triggered the merge. Priority order:
    # DNI > exact-name > fuzzy.
    dni_buckets = _cluster_by_dni(refs)
    dni_intersects = False
    for i in group:
        dni_value = refs[i].dni
        if dni_value is not None and len(dni_buckets.get(dni_value, [])) >= 2:
            dni_intersects = True
            break
    name_buckets = _cluster_by_exact_name(refs)
    name_intersects = any(
        len(name_buckets.get(_normalise_name(refs[i].name), [])) >= 2
        for i in group
    )

    if dni_intersects:
        return ("auto_merged", "dni_exact_match", best_score)
    if name_intersects:
        return ("auto_merged", "exact_name_match", best_score)
    # Pure fuzzy union — at least one pair scored >= threshold.
    return ("auto_merged", "fuzzy_name_match", best_score)


def dedup_volunteers(
    refs: Sequence[VolunteerRef],
    *,
    fuzzy_threshold: int = DEFAULT_FUZZY_THRESHOLD,
) -> list[MergedCluster]:
    """Run the dedup pipeline and return a list of :class:`MergedCluster`.

    The function is pure: same input -> same output, no side
    effects on its arguments. The only side effect is a single
    ``log_safe("dedup.volunteer.summary", ...)`` event that emits
    the cluster count + decision counts (NEVER raw DNI values) so
    operators can confirm the run on the dashboard.

    Args:
        refs: the free-text volunteer references to cluster.
        fuzzy_threshold: 0..100; pairs of refs whose ``WRatio`` is
            at or above this value collapse. Defaults to
            :data:`DEFAULT_FUZZY_THRESHOLD` (85).

    Returns:
        A list of :class:`MergedCluster` ordered by the earliest
        input index in each cluster.
    """
    if not 0 <= fuzzy_threshold <= 100:
        raise ValueError(
            f"fuzzy_threshold must be in [0, 100]; got {fuzzy_threshold}"
        )

    # Union-find seeded by the exact-name and DNI pre-passes; the
    # fuzzy stage then unions any additional pairs that score
    # above the threshold. The union-find is the single source of
    # truth for cluster membership — both pre-passes and the fuzzy
    # pass write into the same data structure.
    uf = _UnionFind(len(refs))
    for bucket in _cluster_by_exact_name(refs).values():
        if len(bucket) >= 2:
            for i in bucket[1:]:
                uf.union(bucket[0], i)
    for bucket in _cluster_by_dni(refs).values():
        if len(bucket) >= 2:
            for i in bucket[1:]:
                uf.union(bucket[0], i)
    for i, j in _fuzzy_candidate_pairs(refs, threshold=fuzzy_threshold):
        uf.union(i, j)

    raw_clusters = _build_clusters(refs, uf, _threshold=fuzzy_threshold)

    # Materialise each raw cluster into a ``MergedCluster``. The
    # DNI-collision check runs INSIDE this loop so an
    # ambiguous-DNI cluster becomes one ``needs_review`` cluster
    # PER ref (the operator sees each row on its own line in the
    # review output, never as a single merged blob).
    output: list[MergedCluster] = []
    ambiguous_dni_count = 0
    auto_merged_count = 0
    unique_count = 0
    for group in raw_clusters:
        resolved_dni, is_ambiguous = _resolve_dni(group, refs)
        if is_ambiguous:
            # Break the cluster: each ref becomes its own
            # ``needs_review`` cluster so the operator can confirm
            # or override the merge one row at a time.
            ambiguous_dni_count += len(group)
            for idx in group:
                ref = refs[idx]
                output.append(
                    MergedCluster(
                        canonical_name=ref.name,
                        dni=None,
                        sources=[ref],
                        decision="needs_review",
                        reason="ambiguous_dni_collision",
                        confidence=None,
                    )
                )
            continue
        decision, reason, confidence = _cluster_decision(
            group, refs, _threshold=fuzzy_threshold
        )
        if decision == "unique":
            unique_count += 1
        else:
            auto_merged_count += 1
        output.append(
            MergedCluster(
                canonical_name=refs[group[0]].name,
                dni=resolved_dni,
                sources=[refs[i] for i in group],
                decision=decision,
                reason=reason,
                confidence=confidence,
            )
        )

    # Single summary event — closed vocabulary, no PII. The event
    # name follows the ``<scope>.<event>`` convention used
    # elsewhere (``sync.applied``, ``voluntario.deactivated``, …).
    # Counts only — never source values.
    log_safe(
        "dedup.volunteer.summary",
        input_count=len(refs),
        cluster_count=len(output),
        auto_merged_count=auto_merged_count,
        needs_review_count=ambiguous_dni_count,
        unique_count=unique_count,
        fuzzy_threshold=fuzzy_threshold,
    )

    return output


__all__ = [
    "DEFAULT_FUZZY_THRESHOLD",
    "Decision",
    "MergedCluster",
    "Reason",
    "VolunteerRef",
    "dedup_volunteers",
]

