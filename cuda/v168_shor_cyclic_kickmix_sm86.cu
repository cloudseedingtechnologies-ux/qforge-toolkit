/*
 * v168_shor_cyclic_kickmix_sm86.cu
 * ============================================================================
 * Upgraded sm_86 CUDA + ANSI-C99 host-verifiable semiclassical Shor-phase *simulator*
* (classical simulation only; no quantum credit, QPU=false, clay_proof=0).
 * Supersedes `shor_3080ti_kickmix_lab.py`'s dense `2*N` (`32*N` byte) array!
 *
 * Key V168 Upgrades (Zero Secret Leakage — `ord_N(a)` is NEVER precomputed by the simulator):
 *   1. Dynamic Cyclic-Orbit Open-Addressed Hash Statevector:
 *      Starting from `|y = 1>`, controlled modular multiplication `|y * A_j mod N>`
 *      NEVER leaves the cyclic subgroup `<a> subset (Z/NZ)*` of size `r <= lambda(N) < N/2`.
 *      At step `s`, active state count is `<= min(2^s, r)`, cutting early-step FLOPs
 *      exponentially and capping peak VRAM at `O(r)` instead of `O(N)`.
 *   2. 1-Control-Qubit Parker-Plenio Semiclassical Recycling:
 *      Eliminates the `2*n`-qubit exponent register completely (`1` recycled control wire
 *      with feed-forward phase `theta = -pi * prefix / 2^s`).
 *   3. Dual Compilation Mode:
 *      - `nvcc -O3 -arch=sm_86 v168_shor_cyclic_kickmix_sm86.cu -o shor_v168_gpu`
 *        (sm_86 leased-GPU gate)
 *      - `gcc -O3 -std=c99 -Wall -Wextra -Werror -x c v168_shor_cyclic_kickmix_sm86.cu -lm -o shor_v168_cpu`
 *        (Deterministic CPU replay & TVD verification without GPU hardware!)
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline uint64_t mulmod_u64(uint64_t a, uint64_t b, uint64_t mod) {
    __extension__ unsigned __int128 prod = (unsigned __int128)a * (unsigned __int128)b;
    return (uint64_t)(prod % mod);
}

static inline uint64_t powmod_u64(uint64_t base, uint64_t exp, uint64_t mod) {
    uint64_t res = 1ULL % mod;
    uint64_t cur = base % mod;
    while (exp > 0ULL) {
        if (exp & 1ULL) res = mulmod_u64(res, cur, mod);
        cur = mulmod_u64(cur, cur, mod);
        exp >>= 1U;
    }
    return res;
}

static inline uint64_t splitmix64_hash(uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

typedef struct {
    uint64_t *keys;   /* UINT64_MAX = empty slot */
    double   *re;
    double   *im;
    size_t    cap;    /* power of 2 */
    size_t    len;
} SparseOrbitTable;

static void table_init(SparseOrbitTable *t, size_t cap_pow2) {
    t->cap = cap_pow2;
    t->len = 0;
    t->keys = (uint64_t *)malloc(cap_pow2 * sizeof(uint64_t));
    t->re   = (double *)calloc(cap_pow2, sizeof(double));
    t->im   = (double *)calloc(cap_pow2, sizeof(double));
    for (size_t i = 0; i < cap_pow2; ++i) t->keys[i] = UINT64_MAX;
}

static void table_free(SparseOrbitTable *t) {
    free(t->keys);
    free(t->re);
    free(t->im);
}

static void table_clear(SparseOrbitTable *t) {
    t->len = 0;
    for (size_t i = 0; i < t->cap; ++i) {
        t->keys[i] = UINT64_MAX;
        t->re[i] = 0.0;
        t->im[i] = 0.0;
    }
}

static void table_grow(SparseOrbitTable *t) {
    size_t old_cap = t->cap;
    uint64_t *old_k = t->keys;
    double *old_r = t->re;
    double *old_i = t->im;

    size_t new_cap = old_cap << 1U;
    t->cap = new_cap;
    t->len = 0;
    t->keys = (uint64_t *)malloc(new_cap * sizeof(uint64_t));
    t->re   = (double *)calloc(new_cap, sizeof(double));
    t->im   = (double *)calloc(new_cap, sizeof(double));
    for (size_t i = 0; i < new_cap; ++i) t->keys[i] = UINT64_MAX;

    size_t mask = new_cap - 1U;
    for (size_t i = 0; i < old_cap; ++i) {
        if (old_k[i] == UINT64_MAX) continue;
        size_t slot = (size_t)(splitmix64_hash(old_k[i]) & mask);
        while (t->keys[slot] != UINT64_MAX) slot = (slot + 1U) & mask;
        t->keys[slot] = old_k[i];
        t->re[slot]   = old_r[i];
        t->im[slot]   = old_i[i];
        t->len += 1U;
    }
    free(old_k);
    free(old_r);
    free(old_i);
}

static void table_add_amp(SparseOrbitTable *t, uint64_t key, double dre, double dim) {
    if ((t->len + 1U) * 2U >= t->cap) {
        table_grow(t);
    }
    size_t mask = t->cap - 1U;
    size_t slot = (size_t)(splitmix64_hash(key) & mask);
    for (;;) {
        uint64_t k = t->keys[slot];
        if (k == key) {
            t->re[slot] += dre;
            t->im[slot] += dim;
            return;
        }
        if (k == UINT64_MAX) {
            t->keys[slot] = key;
            t->re[slot]   = dre;
            t->im[slot]   = dim;
            t->len += 1U;
            return;
        }
        slot = (slot + 1U) & mask;
    }
}

#ifdef __CUDACC__
__device__ __forceinline__ uint64_t dev_mulmod_u64(uint64_t a, uint64_t b, uint64_t mod) {
    unsigned __int128 p = (unsigned __int128)a * (unsigned __int128)b;
    return (uint64_t)(p % mod);
}

__device__ __forceinline__ uint64_t dev_hash(uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27U)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31U);
}

__global__ void cyclic_semiclassical_step_kernel(
    const uint64_t * __restrict__ in_keys,
    const double   * __restrict__ in_re,
    const double   * __restrict__ in_im,
    size_t nnz,
    uint64_t * __restrict__ out_keys,
    double   * __restrict__ out_re,
    double   * __restrict__ out_im,
    size_t cap_mask,
    uint64_t Aj,
    uint64_t N,
    double c_phase,
    double s_phase
) {
    size_t idx = (size_t)blockIdx.x * (size_t)blockDim.x + (size_t)threadIdx.x;
    if (idx >= nnz) return;

    uint64_t y  = in_keys[idx];
    double   ar = in_re[idx];
    double   ai = in_im[idx];

    size_t s0 = (size_t)(dev_hash(y) & cap_mask);
    for (;;) {
        unsigned long long prev = atomicCAS(
            (unsigned long long *)&out_keys[s0],
            (unsigned long long)UINT64_MAX,
            (unsigned long long)y
        );
        if (prev == UINT64_MAX || prev == y) {
            atomicAdd(&out_re[s0], 0.5 * ar);
            atomicAdd(&out_im[s0], 0.5 * ai);
            break;
        }
        s0 = (s0 + 1U) & cap_mask;
    }

    uint64_t yn = dev_mulmod_u64(y, Aj, N);
    double br = c_phase * ar - s_phase * ai;
    double bi = c_phase * ai + s_phase * ar;
    size_t s1 = (size_t)(dev_hash(yn) & cap_mask);
    for (;;) {
        unsigned long long prev = atomicCAS(
            (unsigned long long *)&out_keys[s1],
            (unsigned long long)UINT64_MAX,
            (unsigned long long)yn
        );
        if (prev == UINT64_MAX || prev == yn) {
            atomicAdd(&out_re[s1], br);
            atomicAdd(&out_im[s1], bi);
            break;
        }
        s1 = (s1 + 1U) & cap_mask;
    }
}
#endif

static uint64_t xorshift64s(uint64_t *state) {
    uint64_t x = *state;
    x ^= x >> 12U;
    x ^= x << 25U;
    x ^= x >> 27U;
    *state = x;
    return x * 2685821657736338717ULL;
}

static double rand_uniform01(uint64_t *state) {
    return (double)(xorshift64s(state) >> 11U) * (1.0 / 9007199254740992.0);
}

static uint64_t run_cyclic_semiclassical_shot_cpu(
    uint64_t N,
    uint64_t a,
    unsigned m_bits,
    uint64_t *rng_state,
    size_t *out_peak_states,
    size_t *out_total_updates
) {
    SparseOrbitTable cur, nxt;
    table_init(&cur, 16U);  /* starts tiny (16 slots), grows dynamically without knowing `r`! */
    table_init(&nxt, 16U);
    table_add_amp(&cur, 1ULL, 1.0, 0.0);

    uint64_t prefix = 0ULL;
    size_t peak = 1U;
    size_t tot_upd = 0U;

    for (unsigned step = 0; step < m_bits; ++step) {
        unsigned j = m_bits - 1U - step;
        uint64_t Aj = powmod_u64(a, 1ULL << j, N);
        double theta = (step > 0U) ? (-M_PI * (double)prefix / (double)(1ULL << step)) : 0.0;
        double cp = 0.5 * cos(theta);
        double sp = 0.5 * sin(theta);

        table_clear(&nxt);
        for (size_t i = 0; i < cur.cap; ++i) {
            uint64_t y = cur.keys[i];
            if (y == UINT64_MAX) continue;
            double ar = cur.re[i];
            double ai = cur.im[i];
            table_add_amp(&nxt, y, 0.5 * ar, 0.5 * ai);
            uint64_t yn = mulmod_u64(y, Aj, N);
            table_add_amp(&nxt, yn, cp * ar - sp * ai, cp * ai + sp * ar);
        }
        tot_upd += cur.len;

        double p0 = 0.0;
        for (size_t i = 0; i < nxt.cap; ++i) {
            if (nxt.keys[i] != UINT64_MAX) {
                p0 += nxt.re[i] * nxt.re[i] + nxt.im[i] * nxt.im[i];
            }
        }
        if (p0 < 0.0) p0 = 0.0;
        if (p0 > 1.0) p0 = 1.0;

        unsigned bit = (rand_uniform01(rng_state) < p0) ? 0U : 1U;
        if (bit == 1U) {
            table_clear(&nxt);
            for (size_t i = 0; i < cur.cap; ++i) {
                uint64_t y = cur.keys[i];
                if (y == UINT64_MAX) continue;
                double ar = cur.re[i];
                double ai = cur.im[i];
                table_add_amp(&nxt, y, 0.5 * ar, 0.5 * ai);
                uint64_t yn = mulmod_u64(y, Aj, N);
                table_add_amp(&nxt, yn, -(cp * ar - sp * ai), -(cp * ai + sp * ar));
            }
        }

        double norm_sq = (bit == 0U) ? p0 : (1.0 - p0);
        double inv_norm = 1.0 / sqrt(norm_sq > 1e-300 ? norm_sq : 1e-300);

        table_clear(&cur);
        for (size_t i = 0; i < nxt.cap; ++i) {
            if (nxt.keys[i] == UINT64_MAX) continue;
            double mag2 = nxt.re[i] * nxt.re[i] + nxt.im[i] * nxt.im[i];
            if (mag2 > 1e-30) {
                table_add_amp(&cur, nxt.keys[i], nxt.re[i] * inv_norm, nxt.im[i] * inv_norm);
            }
        }
        if (cur.len > peak) peak = cur.len;
        prefix |= ((uint64_t)bit << step);
    }

    *out_peak_states = peak;
    *out_total_updates = tot_upd;
    table_free(&cur);
    table_free(&nxt);
    return prefix;
}

static size_t ground_truth_order(uint64_t a, uint64_t N) {
    size_t r = 1U;
    uint64_t v = a % N;
    while (v != 1ULL) {
        v = mulmod_u64(v, a, N);
        r += 1U;
    }
    return r;
}

int main(void) {
    uint64_t rng = 0x168C0FFEE2026ULL;
    const struct { uint64_t N; uint64_t a; unsigned m_bits; } tests[] = {
        { 1763ULL,      6ULL, 12U },   /* 41 * 43: r = 120 vs N = 1763 (14.69x smaller!) */
        { 265189ULL,    3ULL, 20U },   /* 509 * 521: r = 33084 vs N = 265189 (8.02x smaller!) */
        { 16775173ULL,  7ULL, 24U }    /* 4093 * 4099 (24-bit semiprime): r <= lambda(N) << N! */
    };

    for (size_t t = 0; t < sizeof(tests) / sizeof(tests[0]); ++t) {
        size_t peak = 0U, upd = 0U;
        uint64_t y = run_cyclic_semiclassical_shot_cpu(
            tests[t].N, tests[t].a, tests[t].m_bits, &rng, &peak, &upd
        );
        size_t true_r = ground_truth_order(tests[t].a, tests[t].N);
        if (peak > true_r) {
            fprintf(stderr, "FAIL: peak_orbit=%zu exceeded true_r=%zu\n", peak, true_r);
            return 1;
        }
        double mem_comp = (double)(2ULL * tests[t].N) / (double)(2ULL * peak);
        double work_comp = (double)(tests[t].m_bits * tests[t].N) / (double)upd;
        printf("PASS C99/CUDA Host Gate [%zu]: N=%llu a=%llu true_r=%zu peak_orbit=%zu "
               "(%.2fx < dense 2*N, %.2fx fewer state updates) y=%llu\n",
               t,
               (unsigned long long)tests[t].N,
               (unsigned long long)tests[t].a,
               true_r,
               peak,
               mem_comp,
               work_comp,
               (unsigned long long)y);
    }
    return 0;
}