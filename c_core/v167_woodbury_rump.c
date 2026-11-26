
#if defined(__clang__)
#pragma STDC FENV_ACCESS ON
#endif
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

// Computes unit-lower sparse LDL^T of the (D+1)x(D+1) symmetric bordered matrix K_aug:
//   Leading D x D: sparse symmetric M_s (CSC lower triangle)
//   Last row/col D: vector x[0..D-1], and bottom-right corner K_aug[D, D] = -1.0 / c_defl
// Because x is placed in row D (the VERY LAST index), eliminating columns 0..D-1
// introduces ZERO extra fill-in from x!
// Also computes Rump/Higham hardware FE_UPWARD infinity-norm backward error bound:
//   ||Delta_K||_inf <= gamma_{D+2} * || |L_aug| |D_aug| |L_aug|^T ||_inf
// and certifies via Sturm/Weyl separation (by checking both K_aug - alpha*I_{D+1} and K_aug + alpha*I_{D+1},
// or checking exact inertia stability under ||Delta_K||_inf < alpha_shift)!
// Wait: to guarantee NO eigenvalue of K_aug crosses 0 under perturbation ||Delta_K||_inf <= err_hi,
// it suffices to run LDL^T TWICE — once on (K_aug - alpha_shift * I_{D+1}) and once on
// (K_aug + alpha_shift * I_{D+1})!
// PROOF (Weyl Monotonicity — Ironclad & Pivot-Sign-Agnostic!):
//   1. Let K_- = K_aug - alpha * I. Computed LDL^T gives K_- + Delta_- = L_- D_- L_-^T
//      with ||Delta_-||_inf <= err_minus. If err_minus < alpha, then K_- + Delta_- <= K_aug
//      (since alpha*I + Delta_- > 0 SPD!), so by Weyl monotonicity:
//          n_-(K_aug) <= n_-(K_- + Delta_-) = neg_pivots(D_-)!
//   2. Similarly, for K_+ = K_aug + alpha * I, if err_plus < alpha, then K_aug <= K_+ + Delta_+,
//      so n_-(K_+ + Delta_+) <= n_-(K_aug)!
//   3. Specifically, to prove M + c*x*x^T > 0 SPD (which only needs the UPPER bound n_-(M + c*x*x^T) == 0,
//      i.e., n_-(K_aug) <= 1 because K_aug[D,D] = -1/c < 0 already forces n_-(K_aug) >= 1 by Cauchy interlacing!):
//      Let K_- = [ M - alpha*I     x          ]
//                [    x^T       -1/c - alpha  ].
//      Notice K_aug - K_- = alpha * I_{D+1}.
//      If LDL^T on K_- succeeds without zero/tiny pivot breakdown and err_minus < alpha, then
//      K_aug = (K_- + Delta_-) + (alpha * I_{D+1} - Delta_-).
//      Since ||Delta_-||_inf <= err_minus < alpha, (alpha * I_{D+1} - Delta_-) is STRICTLY POSITIVE DEFINITE!
//      Adding a strictly positive definite matrix CANNOT increase the number of negative eigenvalues!
//      Therefore:
//          n_-(K_aug) <= n_-(K_- + Delta_-) = neg_pivots(D_-)!
//      And if neg_pivots(D_-) == 1, then since K_aug[D,D] = -1/c < 0 implies n_-(K_aug) >= 1,
//      we have PROVED `n_-(K_aug) == 1`, hence by Haynsworth's theorem `n_-(M + c*x*x^T) == 0`,
//      i.e. `M + c*x*x^T > 0` STRICTLY POSITIVE DEFINITE!
//
// Look how clean, exact, and airtight that theorem is: ONE sparse bordered LDL^T + ONE FE_UPWARD pass!

int sparse_bordered_ldlt_cert(
    int D,
    const int32_t *A_col_ptr,
    const int32_t *A_row_idx,
    const double  *A_val,
    const double  *x_vec,      // length D (or NULL if pure D x D SPD check!)
    double         corner_dd,  // -1.0 / c_defl - alpha_shift (ignored if x_vec == NULL)
    int64_t        max_L_nnz,
    int64_t       *out_L_nnz,
    int32_t       *out_neg_pivots,
    double        *out_err_bound,
    double        *out_min_abs_piv
) {
    int N_tot = (x_vec != NULL) ? (D + 1) : D;
    int64_t cap = (int64_t)A_col_ptr[D] * 6 + (int64_t)N_tot * 4 + 4096;
    if (cap > max_L_nnz) cap = max_L_nnz;

    int32_t *L_row   = (int32_t *)malloc((size_t)cap * sizeof(int32_t));
    double  *L_val   = (double  *)malloc((size_t)cap * sizeof(double));
    double  *d_piv   = (double  *)calloc((size_t)N_tot, sizeof(double));
    int64_t *L_start = (int64_t *)calloc((size_t)N_tot, sizeof(int64_t));
    int64_t *L_end   = (int64_t *)calloc((size_t)N_tot, sizeof(int64_t));
    int32_t *head    = (int32_t *)malloc((size_t)N_tot * sizeof(int32_t));
    int32_t *next    = (int32_t *)malloc((size_t)N_tot * sizeof(int32_t));
    int64_t *cur_pos = (int64_t *)malloc((size_t)N_tot * sizeof(int64_t));
    double  *work    = (double  *)calloc((size_t)N_tot, sizeof(double));
    int32_t *mark    = (int32_t *)malloc((size_t)N_tot * sizeof(int32_t));
    int32_t *pat     = (int32_t *)malloc((size_t)N_tot * sizeof(int32_t));

    if (!L_row || !L_val || !d_piv || !L_start || !L_end || !head || !next || !cur_pos || !work || !mark || !pat) {
        free(L_row); free(L_val); free(d_piv); free(L_start); free(L_end);
        free(head); free(next); free(cur_pos); free(work); free(mark); free(pat);
        return -3;
    }
    for (int i = 0; i < N_tot; i++) { head[i] = -1; next[i] = -1; mark[i] = -1; }

    int64_t L_nnz = 0;
    int32_t neg_cnt = 0;
    double min_abs_p = 1e300;
    int status = 0;

    for (int j = 0; j < N_tot; j++) {
        int pat_len = 0;
        if (j < D) {
            for (int32_t p = A_col_ptr[j]; p < A_col_ptr[j + 1]; p++) {
                int32_t i = A_row_idx[p];
                if (i < j) continue;
                if (mark[i] != j) { mark[i] = j; pat[pat_len++] = i; work[i] = A_val[p]; }
                else              { work[i] += A_val[p]; }
            }
            if (x_vec != NULL && x_vec[j] != 0.0) {
                int32_t i = D;
                if (mark[i] != j) { mark[i] = j; pat[pat_len++] = i; work[i] = x_vec[j]; }
                else              { work[i] += x_vec[j]; }
            }
        } else {
            mark[D] = D; pat[pat_len++] = D; work[D] = corner_dd;
        }
        if (mark[j] != j) { mark[j] = j; pat[pat_len++] = j; work[j] = 0.0; }

        int32_t k = head[j];
        head[j] = -1;
        while (k != -1) {
            int32_t nxt_k = next[k];
            int64_t pk = cur_pos[k];
            double ljk = L_val[pk];
            double dk_ljk = d_piv[k] * ljk;
            int64_t end_k = L_end[k];
            for (int64_t q = pk; q < end_k; q++) {
                int32_t i = L_row[q];
                double prod = dk_ljk * L_val[q];
                if (mark[i] != j) { mark[i] = j; pat[pat_len++] = i; work[i] = -prod; }
                else              { work[i] -= prod; }
            }
            pk++;
            if (pk < end_k) {
                cur_pos[k] = pk;
                int32_t r_next = L_row[pk];
                next[k] = head[r_next];
                head[r_next] = k;
            }
            k = nxt_k;
        }

        double dj = work[j];
        if (!isfinite(dj) || fabs(dj) < 1e-15) { status = -1; break; }
        if (dj < 0.0) neg_cnt++;
        if (fabs(dj) < min_abs_p) min_abs_p = fabs(dj);
        d_piv[j] = dj;
        double inv_dj = 1.0 / dj;

        int off_cnt = 0;
        for (int idx = 0; idx < pat_len; idx++) {
            int32_t i = pat[idx];
            if (i <= j || work[i] == 0.0) continue;
            pat[off_cnt++] = i;
        }
        // Shell sort column pattern
        for (int gap = off_cnt >> 1; gap > 0; gap >>= 1) {
            for (int a = gap; a < off_cnt; a++) {
                int32_t tmp = pat[a];
                int b = a;
                while (b >= gap && pat[b - gap] > tmp) { pat[b] = pat[b - gap]; b -= gap; }
                pat[b] = tmp;
            }
        }

        if (L_nnz + off_cnt + 1 > cap) {
            int64_t new_cap = cap * 2;
            if (new_cap < L_nnz + off_cnt + 1) new_cap = L_nnz + off_cnt + 1;
            if (new_cap > max_L_nnz) { status = -3; break; }
            int32_t *nr = (int32_t *)realloc(L_row, (size_t)new_cap * sizeof(int32_t));
            double  *nv = (double  *)realloc(L_val, (size_t)new_cap * sizeof(double));
            if (!nr || !nv) { status = -3; break; }
            L_row = nr; L_val = nv; cap = new_cap;
        }

        L_start[j] = L_nnz;
        // Unit diagonal L[j, j] = 1.0
        L_row[L_nnz] = j;
        L_val[L_nnz] = 1.0;
        L_nnz++;
        for (int idx = 0; idx < off_cnt; idx++) {
            int32_t i = pat[idx];
            L_row[L_nnz] = i;
            L_val[L_nnz] = work[i] * inv_dj;
            L_nnz++;
        }
        L_end[j] = L_nnz;
        if (off_cnt > 0) {
            cur_pos[j] = L_start[j] + 1;
            int32_t r0 = L_row[cur_pos[j]];
            next[j] = head[r0];
            head[r0] = j;
        }
    }

    if (status == 0) {
        // Hardware FE_UPWARD Rump/Higham componentwise backward error bound on || |L| |D| |L|^T ||_inf:
        // Step 1: col_sum[k] = |d_k| * sum_{i >= k} |L[i, k]|   (since L is stored by columns k, this is a contiguous loop!)
        // Wait: (|L| |D| |L|^T 1)_i = sum_{k <= i} |L[i, k]| * |d_k| * (sum_{m >= k} |L[m, k]| ... NO! |L|^T 1 at index k is sum_{m=0}^{N_tot-1} |L[m, k]| = sum_{m >= k} |L[m, k]| because L is lower triangular!!).
        // YES! (|L|^T 1)_k = sum_{m=k}^{N_tot-1} |L[m, k]|!
        // Then w_k = |d_k| * (|L|^T 1)_k, and row_sum[i] = sum_{k=0}^{i} |L[i, k]| * w_k!
        int saved = fegetround();
        if (fesetround(FE_UPWARD) != 0) {
            status = -2;
        } else {
            double *row_acc = (double *)calloc((size_t)N_tot, sizeof(double));
            int32_t *row_deg = (int32_t *)calloc((size_t)N_tot, sizeof(int32_t));
            if (!row_acc || !row_deg) {
                free(row_acc); free(row_deg);
                fesetround(saved);
                status = -3;
            } else {
                for (int k = 0; k < N_tot; k++) {
                    double l_col_1norm = 0.0;
                    for (int64_t q = L_start[k]; q < L_end[k]; q++) {
                        l_col_1norm += fabs(L_val[q]);
                        row_deg[L_row[q]]++;
                    }
                    double wk = fabs(d_piv[k]) * l_col_1norm;
                    for (int64_t q = L_start[k]; q < L_end[k]; q++) {
                        int32_t i = L_row[q];
                        row_acc[i] += fabs(L_val[q]) * wk;
                    }
                }
                double norm_inf = 0.0;
                int max_deg = 1;
                for (int i = 0; i < N_tot; i++) {
                    if (row_acc[i] > norm_inf) norm_inf = row_acc[i];
                    if (row_deg[i] > max_deg) max_deg = row_deg[i];
                }
                free(row_acc); free(row_deg);

                // Higham (2002) Thm 10.3 / sparse column-elimination count: at most (max_deg + 2) ops per entry
                double u = ldexp(1.0, -53);
                double ku = (double)(max_deg + 2) * u;
                if (ku >= 0.5) {
                    status = -2;
                } else {
                    double gamma_hi = ku / (-((-1.0) + ku));
                    *out_err_bound = gamma_hi * norm_inf;
                    *out_L_nnz = L_nnz;
                    *out_neg_pivots = neg_cnt;
                    *out_min_abs_piv = min_abs_p;
                }
                fesetround(saved);
            }
        }
    }

    free(L_row); free(L_val); free(d_piv); free(L_start); free(L_end);
    free(head); free(next); free(cur_pos); free(work); free(mark); free(pat);
    return status;
}

// Fast C99 sector enumerator & sparse COO builder matching a prior j1j2 C enumerator byte-for-byte
static inline uint64_t rev_u64(uint64_t x, int N) {
    uint64_t r = 0;
    for (int i = 0; i < N; i++) { r = (r << 1) | (x & 1ULL); x >>= 1; }
    return r;
}
static inline uint64_t rotl1_u64(uint64_t x, int N, uint64_t m) {
    return ((x << 1) | (x >> (N - 1))) & m;
}
static inline uint64_t next_comb_u64(uint64_t v) {
    uint64_t t = v | (v - 1);
    return (t + 1) | (((~t & -~t) - 1) >> (__builtin_ctzll(v) + 1));
}
static inline int repnorm_c(int N, int kpi, int p, int z, uint64_t m, uint64_t s) {
    uint64_t base[4]; int bch[4]; int nb = 0;
    base[nb] = s; bch[nb++] = 1;
    uint64_t rs = rev_u64(s, N);
    if (p) { base[nb] = rs; bch[nb++] = p; }
    if (z) { base[nb] = (~s) & m; bch[nb++] = z; }
    if (p && z) { base[nb] = (~rs) & m; bch[nb++] = p * z; }
    int sum = 0;
    for (int b = 0; b < nb; b++) {
        uint64_t c = base[b];
        for (int r = 0; r < N; r++) {
            if (c < s) return 0;
            if (c == s) sum += bch[b] * ((kpi && (r & 1)) ? -1 : 1);
            c = rotl1_u64(c, N, m);
        }
    }
    return sum > 0 ? sum : 0;
}
static inline uint64_t canon_c(int N, int kpi, int p, int z, uint64_t m, uint64_t s, int *chi) {
    uint64_t best = s; int bc = 1;
    uint64_t base[4]; int bch[4]; int nb = 0;
    base[nb] = s; bch[nb++] = 1;
    uint64_t rs = rev_u64(s, N);
    if (p) { base[nb] = rs; bch[nb++] = p; }
    if (z) { base[nb] = (~s) & m; bch[nb++] = z; }
    if (p && z) { base[nb] = (~rs) & m; bch[nb++] = p * z; }
    for (int b = 0; b < nb; b++) {
        uint64_t c = base[b];
        for (int r = 0; r < N; r++) {
            int ch = bch[b] * ((kpi && (r & 1)) ? -1 : 1);
            if (c < best) { best = c; bc = ch; }
            c = rotl1_u64(c, N, m);
        }
    }
    *chi = bc;
    return best;
}
static inline int64_t bsearch_u64(const uint64_t *reps, int64_t D, uint64_t x) {
    int64_t lo = 0, hi = D;
    while (lo < hi) {
        int64_t mid = lo + ((hi - lo) >> 1);
        if (reps[mid] < x) lo = mid + 1; else hi = mid;
    }
    return (lo < D && reps[lo] == x) ? lo : -1;
}

int64_t build_j1j2_sector_reps(int N, int nup, int kpi, int p, int z, uint64_t *out_reps, uint8_t *out_norm, int64_t max_D) {
    uint64_t m = (1ULL << N) - 1ULL;
    uint64_t comb = (1ULL << nup) - 1ULL;
    uint64_t last = comb << (N - nup);
    int64_t cnt = 0;
    while (1) {
        int nn = repnorm_c(N, kpi, p, z, m, comb);
        if (nn > 0) {
            if (out_reps != NULL && cnt < max_D) {
                out_reps[cnt] = comb;
                out_norm[cnt] = (uint8_t)nn;
            }
            cnt++;
        }
        if (comb == last) break;
        comb = next_comb_u64(comb);
    }
    return cnt;
}

int64_t build_j1j2_coo(
    int N, int kpi, int p, int z,
    const uint64_t *reps, const uint8_t *norm, int64_t D,
    double g,
    int32_t *row_out, int32_t *col_out, double *val_out, double *absrow_out,
    int64_t max_nnz
) {
    uint64_t m = (1ULL << N) - 1ULL;
    int64_t nnz = 0;
    for (int64_t a = 0; a < D; a++) {
        uint64_t s = reps[a];
        uint64_t r1 = ((s >> 1) | (s << (N - 1))) & m;
        uint64_t r2 = ((s >> 2) | (s << (N - 2))) & m;
        int a1 = __builtin_popcountll((s ^ r1) & m);
        int a2 = __builtin_popcountll((s ^ r2) & m);
        double dg = 0.25 * ((double)(N - 2 * a1) + g * (double)(N - 2 * a2));
        if (nnz < max_nnz) { row_out[nnz] = (int32_t)a; col_out[nnz] = (int32_t)a; val_out[nnz] = dg; }
        nnz++;
        double arow = fabs(dg);
        for (int typ = 1; typ <= 2; typ++) {
            double h = 0.5 * (typ == 1 ? 1.0 : g);
            for (int i = 0; i < N; i++) {
                int j = (i + typ) % N;
                if (((s >> i) & 1ULL) == ((s >> j) & 1ULL)) continue;
                uint64_t sp = s ^ (1ULL << i) ^ (1ULL << j);
                int chi;
                uint64_t rp = canon_c(N, kpi, p, z, m, sp, &chi);
                int64_t b = bsearch_u64(reps, D, rp);
                if (b < 0) continue;
                double v = h * (double)chi * sqrt((double)norm[b] / (double)norm[a]);
                if (nnz < max_nnz) { row_out[nnz] = (int32_t)a; col_out[nnz] = (int32_t)b; val_out[nnz] = v; }
                nnz++;
                arow += fabs(v);
            }
        }
        absrow_out[a] = arow;
    }
    return nnz;
}
