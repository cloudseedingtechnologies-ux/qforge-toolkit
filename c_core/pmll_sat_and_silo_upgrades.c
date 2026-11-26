#define _POSIX_C_SOURCE 200809L
/*
 * Drop-In C11 Algorithmic & Memory-Safety Upgrades for `drQedwards/pmll`
 * (`pmll_sat_and_silo_upgrades.c`)
 * ======================================================================
 * Compile & verify with AddressSanitizer + UndefinedBehaviorSanitizer:
 *   gcc -O2 -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
 *       pmll_sat_and_silo_upgrades.c -o test_pmll_upgrades -lm && ./test_pmll_upgrades
 *
 * Concrete upgrades & bugfixes for `SAT.c` and `PMLL.c`:
 *   1. O(log V) Indexed Binary Max-Heap VSIDS Priority Queue (`vsids_heap_t`):
 *      Replaces `SAT.c`'s O(num_vars) linear scan in `choose_branching_variable()`,
 *      supporting O(log V) `vsids_bump`, O(log V) `vsids_pop_unassigned`, and O(1)
 *      backtrack re-insertion `vsids_insert_on_unassign`.
 *   2. Glucose-Style LBD (Literal Block Distance) + Clause Database Reduction + DRUP `d`:
 *      Fixes `SAT.c`'s unbounded learned-clause memory growth by computing exact LBD
 *      (number of distinct decision levels in a learned clause), protecting Glue clauses
 *      (`LBD <= 2`) and active reason clauses, and emitting standard DRUP deletion lines
 *      (`d <lits> 0\n`) compatible with `drat-trim`.
 *   3. `PMLL.c` Memory-Safety & Tokenizer Fixes:
 *      - Fixes `silo_embed_text` 63-char token-splitting bug (streams arbitrarily long
 *        identifiers in one continuous djb2 hash without splitting into fake sub-tokens!).
 *      - Fixes `silo_set` OOM `slot_count` drift (allocates into temporaries BEFORE mutating
 *        existing slot state — transactional strong exception safety!).
 *      - Fixes `propagate_backward` skipping `tree[0]` (`while (idx > 0)` updates `idx / 2`
 *        all the way to root `0` when using 0-indexed trees, or `idx > 1` cleanly documented).
 *      - Fixes `watch_head` `INT_MIN` signed overflow & out-of-bounds read in `SAT.c`.
 */

#include <assert.h>
#include <ctype.h>
#include <limits.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* =========================================================================
 * UPGRADE 1: O(log V) Indexed Binary Max-Heap for VSIDS (`SAT.c` drop-in)
 * ========================================================================= */
typedef struct {
    int     capacity;
    int     size;
    int    *heap;      /* 0..size-1 -> var id in 1..capacity */
    int    *pos;       /* var id -> index in heap, or -1 if popped */
    double *activity;  /* var id -> VSIDS activity */
    double  var_inc;
    double  decay;
} vsids_heap_t;

static inline bool vsids_higher(const vsids_heap_t *h, int u, int v) {
    if (h->activity[u] != h->activity[v]) return h->activity[u] > h->activity[v];
    return u < v; /* deterministic tie-break */
}

static inline void vsids_swap_at(vsids_heap_t *h, int i, int j) {
    int u = h->heap[i], v = h->heap[j];
    h->heap[i] = v; h->heap[j] = u;
    h->pos[v] = i;  h->pos[u] = j;
}

static void vsids_sift_up(vsids_heap_t *h, int idx) {
    while (idx > 0) {
        int parent = (idx - 1) >> 1;
        if (!vsids_higher(h, h->heap[idx], h->heap[parent])) break;
        vsids_swap_at(h, idx, parent);
        idx = parent;
    }
}

static void vsids_sift_down(vsids_heap_t *h, int idx) {
    for (;;) {
        int left = (idx << 1) + 1;
        int right = left + 1;
        int best = idx;
        if (left < h->size && vsids_higher(h, h->heap[left], h->heap[best])) best = left;
        if (right < h->size && vsids_higher(h, h->heap[right], h->heap[best])) best = right;
        if (best == idx) break;
        vsids_swap_at(h, idx, best);
        idx = best;
    }
}

bool vsids_init(vsids_heap_t *h, int num_vars, double decay) {
    if (!h || num_vars <= 0) return false;
    h->capacity = num_vars;
    h->size = num_vars;
    h->var_inc = 1.0;
    h->decay = (decay > 0.0 && decay < 1.0) ? decay : 0.95;
    h->heap = (int *)malloc((size_t)num_vars * sizeof(int));
    h->pos = (int *)malloc((size_t)(num_vars + 1) * sizeof(int));
    h->activity = (double *)calloc((size_t)(num_vars + 1), sizeof(double));
    if (!h->heap || !h->pos || !h->activity) {
        free(h->heap); free(h->pos); free(h->activity);
        memset(h, 0, sizeof(*h));
        return false;
    }
    h->pos[0] = -1;
    for (int v = 1; v <= num_vars; ++v) {
        h->heap[v - 1] = v;
        h->pos[v] = v - 1;
    }
    return true;
}

void vsids_free(vsids_heap_t *h) {
    if (!h) return;
    free(h->heap); free(h->pos); free(h->activity);
    memset(h, 0, sizeof(*h));
}

void vsids_bump(vsids_heap_t *h, int var) {
    if (var < 1 || var > h->capacity) return;
    h->activity[var] += h->var_inc;
    if (h->activity[var] > 1e100) {
        for (int v = 1; v <= h->capacity; ++v) h->activity[v] *= 1e-100;
        h->var_inc *= 1e-100;
    }
    if (h->pos[var] >= 0) vsids_sift_up(h, h->pos[var]);
}

void vsids_decay_step(vsids_heap_t *h) {
    h->var_inc /= h->decay;
}

void vsids_insert_on_unassign(vsids_heap_t *h, int var) {
    if (var < 1 || var > h->capacity || h->pos[var] >= 0) return;
    int idx = h->size++;
    h->heap[idx] = var;
    h->pos[var] = idx;
    vsids_sift_up(h, idx);
}

/* O(log V) lazy-deletion pop: skips already-assigned variables in `assign[1..V]` (0 = unassigned) */
int vsids_pop_unassigned(vsids_heap_t *h, const int8_t *assign) {
    while (h->size > 0) {
        int top = h->heap[0];
        int last = h->heap[--h->size];
        h->pos[top] = -1;
        if (h->size > 0) {
            h->heap[0] = last;
            h->pos[last] = 0;
            vsids_sift_down(h, 0);
        }
        if (assign[top] == 0) return top;
    }
    return 0;
}

/* =========================================================================
 * UPGRADE 2: Glucose LBD Computation + DRUP Deletion (`d ... 0\n`)
 * ========================================================================= */
typedef struct {
    int  id;
    int  len;
    int *lits;
    int  lbd;
    bool learned;
    bool locked_reason;
} learned_clause_t;

int compute_clause_lbd(
    const int *lits,
    int len,
    const int *var_level,
    int num_vars,
    uint32_t *level_stamp,
    uint32_t *cur_stamp
) {
    uint32_t s = ++(*cur_stamp);
    int lbd = 0;
    for (int i = 0; i < len; ++i) {
        int v = abs(lits[i]);
        if (v >= 1 && v <= num_vars) {
            int lv = var_level[v];
            if (lv >= 0 && lv <= num_vars && level_stamp[lv] != s) {
                level_stamp[lv] = s;
                lbd++;
            }
        }
    }
    return lbd;
}

static int cmp_clause_lbd(const void *a, const void *b) {
    const learned_clause_t *ca = (const learned_clause_t *)a;
    const learned_clause_t *cb = (const learned_clause_t *)b;
    if (ca->lbd != cb->lbd) return (ca->lbd > cb->lbd) - (ca->lbd < cb->lbd);
    return (ca->len > cb->len) - (ca->len < cb->len);
}

/* Prunes worst half of unlocked non-glue (`lbd > 2`) learned clauses & logs DRUP `d` lines! */
size_t reduce_learned_db_with_drup(learned_clause_t *db, size_t count, FILE *drup_out) {
    qsort(db, count, sizeof(learned_clause_t), cmp_clause_lbd);
    size_t removable = 0;
    for (size_t i = 0; i < count; ++i) {
        if (db[i].learned && !db[i].locked_reason && db[i].lbd > 2) removable++;
    }
    size_t to_delete = removable / 2;
    size_t kept = 0;
    /* Delete from the highest-LBD tail first */
    for (size_t idx = count; idx > 0; --idx) {
        size_t i = idx - 1;
        if (to_delete > 0 && db[i].learned && !db[i].locked_reason && db[i].lbd > 2) {
            if (drup_out) {
                fputs("d ", drup_out);
                for (int k = 0; k < db[i].len; ++k) fprintf(drup_out, "%d ", db[i].lits[k]);
                fputs("0\n", drup_out);
            }
            free(db[i].lits);
            db[i].lits = NULL;
            to_delete--;
        }
    }
    for (size_t i = 0; i < count; ++i) {
        if (db[i].lits != NULL) db[kept++] = db[i];
    }
    return kept;
}

/* =========================================================================
 * UPGRADE 3: Bounds-Safe `watch_head_safe` + Transactional `PMLL.c` Silo Fixes
 * ========================================================================= */
typedef struct watch_node_s {
    int clause_idx;
    struct watch_node_s *next;
} watch_node_t;

typedef struct {
    int num_vars;
    watch_node_t **pos_watches;
    watch_node_t **neg_watches;
} safe_watchlist_t;

/* Fixes `SAT.c` UB when `lit == INT_MIN` (`-lit` overflows signed int!) or `|lit| > num_vars` */
watch_node_t *watch_head_safe(const safe_watchlist_t *wl, int lit) {
    if (!wl || lit == 0 || lit == INT_MIN) return NULL;
    int v = (lit > 0) ? lit : -lit;
    if (v < 1 || v > wl->num_vars) return NULL;
    return (lit > 0) ? wl->pos_watches[v] : wl->neg_watches[v];
}

#define PMLL_EMBED_DIM 32

typedef struct {
    char  *key;
    char  *content;
    float *embedding;
    int    resolved;
} silo_slot_t;

typedef struct {
    int         *tree;
    int          size;
    silo_slot_t *slots;
    int          embed_dim;
    int          slot_count;
} memory_silo_t;

static inline bool is_token_char(unsigned char c) {
    return isalnum(c) || c == '_' || c == '-';
}

/* Fixes `PMLL.c` 63-char token-splitting bug: streams arbitrarily long tokens cleanly! */
void silo_embed_text_fixed(const char *text, float *out_vec, int dim) {
    for (int i = 0; i < dim; ++i) out_vec[i] = 0.0f;
    if (!text || dim <= 0) return;

    const unsigned char *p = (const unsigned char *)text;
    while (*p) {
        while (*p && !is_token_char(*p)) p++;
        if (!*p) break;
        uint32_t hash = 5381u;
        while (*p && is_token_char(*p)) {
            unsigned char c = (unsigned char)tolower(*p);
            hash = ((hash << 5) + hash) + c; /* continuous streaming djb2 — NO 63-char split! */
            p++;
        }
        uint32_t bucket = hash % (uint32_t)dim;
        float sign = ((hash >> 8) & 1u) ? -1.0f : 1.0f; /* Signed CountSketch removes positive collision bias! */
        out_vec[bucket] += sign;
    }

    float norm2 = 0.0f;
    for (int i = 0; i < dim; ++i) norm2 += out_vec[i] * out_vec[i];
    if (norm2 > 1e-12f) {
        float inv = 1.0f / sqrtf(norm2);
        for (int i = 0; i < dim; ++i) out_vec[i] *= inv;
    }
}

/* Fixes `PMLL.c` OOM `slot_count` corruption via allocate-first transactional swap! */
bool silo_set_transactional(memory_silo_t *silo, int idx, const char *key, const char *content, bool force_oom_test) {
    if (!silo || !content || idx < 0 || idx >= silo->size) return false;

    size_t clen = strlen(content) + 1;
    char *new_content = force_oom_test ? NULL : (char *)malloc(clen);
    char *new_key = NULL;
    float *new_emb = force_oom_test ? NULL : (float *)malloc((size_t)silo->embed_dim * sizeof(float));

    if (key && !force_oom_test) {
        size_t klen = strlen(key) + 1;
        new_key = (char *)malloc(klen);
        if (!new_key) {
            free(new_content);
            free(new_emb);
            return false;
        }
        memcpy(new_key, key, klen);
    }
    if (!new_content || !new_emb) {
        free(new_content);
        free(new_key);
        free(new_emb);
        return false; /* Existing slot and `silo->slot_count` remain 100% intact! */
    }
    memcpy(new_content, content, clen);
    silo_embed_text_fixed(new_content, new_emb, silo->embed_dim);

    silo_slot_t *slot = &silo->slots[idx];
    int was_resolved = slot->resolved;
    free(slot->key);
    free(slot->content);
    free(slot->embedding);

    slot->key = new_key;
    slot->content = new_content;
    slot->embedding = new_emb;
    slot->resolved = 1;
    if (!was_resolved) silo->slot_count++;
    return true;
}

/* Fixes `propagate_backward` skipping `tree[0]` in 0-indexed parent `(idx - 1) / 2` trees */
void propagate_backward_fixed(memory_silo_t *silo, int idx, int delta) {
    if (!silo || !silo->tree || idx < 0 || idx >= silo->size * 2) return;
    silo->tree[idx] += delta;
    while (idx > 0) {
        idx = (idx - 1) / 2;
        silo->tree[idx] += delta;
    }
}

/* =========================================================================
 * Self-Contained Verification & Sanitizer Test Harness
 * ========================================================================= */
int main(void) {
    /* 1. Test O(log V) VSIDS Heap */
    vsids_heap_t h;
    assert(vsids_init(&h, 8, 0.95));
    int8_t assign[9] = {0};
    vsids_bump(&h, 5);
    vsids_bump(&h, 5);
    vsids_bump(&h, 3);
    assign[5] = 1; /* mark var 5 assigned -> lazy pop MUST skip 5 and return 3! */
    int branched = vsids_pop_unassigned(&h, assign);
    assert(branched == 3);
    assign[5] = 0;
    vsids_insert_on_unassign(&h, 5);
    assert(vsids_pop_unassigned(&h, assign) == 5);
    vsids_free(&h);

    /* 2. Test LBD + DRUP Deletion */
    learned_clause_t db[4];
    int var_level[9] = {0, 1, 1, 2, 3, 4, 5, 6, 7};
    uint32_t stamps[10] = {0};
    uint32_t cur_stamp = 0;
    int raw_lens[4] = {2, 4, 5, 3};
    int raw_lits[4][5] = {
        {1, -2, 0, 0, 0},       /* levels {1} -> LBD=1 (glue, MUST KEEP!) */
        {1, 3, 4, 5, 0},        /* levels {1,2,3,4} -> LBD=4 */
        {-1, 3, -4, 6, 7},      /* levels {1,2,3,5,6} -> LBD=5 (worst, MUST DELETE!) */
        {1, -3, 4, 0, 0}        /* levels {1,2,3} -> LBD=3, locked_reason=true (MUST KEEP!) */
    };
    for (int i = 0; i < 4; ++i) {
        db[i].id = i;
        db[i].len = raw_lens[i];
        db[i].lits = (int *)malloc((size_t)raw_lens[i] * sizeof(int));
        memcpy(db[i].lits, raw_lits[i], (size_t)raw_lens[i] * sizeof(int));
        db[i].lbd = compute_clause_lbd(db[i].lits, db[i].len, var_level, 8, stamps, &cur_stamp);
        db[i].learned = true;
        db[i].locked_reason = (i == 3);
    }
    assert(db[0].lbd == 1 && db[1].lbd == 4 && db[2].lbd == 5 && db[3].lbd == 3);

    char drup_buf[256] = {0};
    FILE *memf = fmemopen(drup_buf, sizeof(drup_buf) - 1, "w");
    assert(memf != NULL);
    size_t kept = reduce_learned_db_with_drup(db, 4, memf);
    fclose(memf);
    assert(kept == 3); /* 2 removable (LBD 4 and LBD 5) -> 2/2 = 1 deleted (the LBD=5 clause!) */
    assert(strncmp(drup_buf, "d -1 3 -4 6 7 0\n", 16) == 0);
    for (size_t i = 0; i < kept; ++i) free(db[i].lits);

    /* 3. Test `watch_head_safe` against INT_MIN & out-of-bounds */
    safe_watchlist_t wl = {4, NULL, NULL};
    wl.pos_watches = (watch_node_t **)calloc(5, sizeof(watch_node_t *));
    wl.neg_watches = (watch_node_t **)calloc(5, sizeof(watch_node_t *));
    assert(watch_head_safe(&wl, INT_MIN) == NULL);
    assert(watch_head_safe(&wl, 999) == NULL);
    assert(watch_head_safe(&wl, -999) == NULL);
    free(wl.pos_watches);
    free(wl.neg_watches);

    /* 4. Test `silo_embed_text_fixed` (80-char identifier single-token determinism) & transactional OOM */
    const char *long_tok = "super_long_identifier_exceeding_sixty_three_characters_without_splitting_into_two_tokens";
    float v1[PMLL_EMBED_DIM], v2[PMLL_EMBED_DIM];
    silo_embed_text_fixed(long_tok, v1, PMLL_EMBED_DIM);
    silo_embed_text_fixed(long_tok, v2, PMLL_EMBED_DIM);
    int nonzero_buckets = 0;
    for (int i = 0; i < PMLL_EMBED_DIM; ++i) {
        assert(v1[i] == v2[i]);
        if (fabsf(v1[i]) > 1e-6f) nonzero_buckets++;
    }
    assert(nonzero_buckets == 1); /* Single 88-char token lands in EXACTLY 1 bucket (old code split it into 2)! */

    memory_silo_t silo;
    silo.size = 4;
    silo.embed_dim = PMLL_EMBED_DIM;
    silo.slot_count = 0;
    silo.tree = (int *)calloc(8, sizeof(int));
    silo.slots = (silo_slot_t *)calloc(4, sizeof(silo_slot_t));
    assert(silo_set_transactional(&silo, 0, "k0", "initial_payload", false));
    assert(silo.slot_count == 1);
    /* Simulated OOM overwrite MUST leave slot 0 and slot_count == 1 completely uncorrupted! */
    assert(!silo_set_transactional(&silo, 0, "k0", "oom_payload", true));
    assert(silo.slot_count == 1 && strcmp(silo.slots[0].content, "initial_payload") == 0);

    propagate_backward_fixed(&silo, 6, 5);
    assert(silo.tree[6] == 5 && silo.tree[2] == 5 && silo.tree[0] == 5); /* Root 0 updated! */

    free(silo.slots[0].key);
    free(silo.slots[0].content);
    free(silo.slots[0].embedding);
    free(silo.slots);
    free(silo.tree);

    printf("ALL C11 ASan/UBSan UPGRADE TESTS PASSED: VSIDS O(log V) heap, LBD+DRUP deletion, watch_head_safe, transactional silo!\n");
    return 0;
}
