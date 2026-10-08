# Retrieval evaluation: `graph_ctx`

Run 2026-10-08T11:45:04+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `4892616568b8` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.569 | 0.833 | 0.914 | 0.685 | 0.699 |

Query latency (embed + search, warm, n=235): p50 367 ms, p95 472 ms.

Median top-1 similarity: answerable 30.829, unanswerable 30.330 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.525 | 0.725 | 0.875 | 0.608 | 0.638 |
| diabetes | 40 | 0.450 | 0.875 | 0.875 | 0.625 | 0.625 |
| hypertension | 43 | 0.628 | 0.930 | 0.977 | 0.765 | 0.782 |
| infections | 44 | 0.614 | 0.841 | 0.955 | 0.722 | 0.728 |
| respiratory | 42 | 0.619 | 0.786 | 0.881 | 0.696 | 0.714 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.605 | 0.840 | 0.926 | 0.717 | 0.721 |
| pmc | 85 | 0.565 | 0.835 | 0.906 | 0.676 | 0.695 |
| who | 43 | 0.512 | 0.814 | 0.907 | 0.642 | 0.668 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.545 | 0.818 | 0.909 | 0.673 | 0.650 |
| contraindication | 20 | 0.500 | 0.800 | 0.850 | 0.625 | 0.650 |
| dose | 24 | 0.625 | 0.958 | 0.958 | 0.774 | 0.770 |
| fact | 60 | 0.567 | 0.800 | 0.883 | 0.670 | 0.712 |
| interaction | 19 | 0.526 | 0.737 | 0.895 | 0.627 | 0.655 |
| recommendation | 64 | 0.594 | 0.859 | 0.953 | 0.706 | 0.707 |

## Missed at 10 (18)

- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0074: (diabetes, who) How often do sulfonylureas cause hypoglycaemia in patients without kidney problems?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0102: (anticoagulation, pmc) By how much do strong CYP3A4 and P-glycoprotein inhibitors such as ketoconazole raise rivaroxaban levels?
- g0114: (anticoagulation, pmc) What is the standard edoxaban dose for atrial fibrillation?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
