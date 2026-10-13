# Retrieval evaluation: `dense_colbert_ctx`

Run 2026-10-13T15:33:02+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `4892616568b8` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.560 | 0.823 | 0.890 | 0.672 | 0.689 |

Query latency (embed + search, warm, n=235): p50 136 ms, p95 174 ms.

Median top-1 similarity: answerable 30.829, unanswerable 30.340 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.475 | 0.700 | 0.825 | 0.560 | 0.585 |
| diabetes | 40 | 0.425 | 0.800 | 0.825 | 0.590 | 0.609 |
| hypertension | 43 | 0.651 | 0.953 | 0.977 | 0.777 | 0.789 |
| infections | 44 | 0.614 | 0.841 | 0.955 | 0.722 | 0.737 |
| respiratory | 42 | 0.619 | 0.810 | 0.857 | 0.698 | 0.712 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.593 | 0.852 | 0.914 | 0.709 | 0.719 |
| pmc | 85 | 0.553 | 0.812 | 0.882 | 0.659 | 0.678 |
| who | 43 | 0.512 | 0.791 | 0.860 | 0.630 | 0.654 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.455 | 0.727 | 0.864 | 0.589 | 0.602 |
| contraindication | 20 | 0.500 | 0.850 | 0.850 | 0.627 | 0.652 |
| dose | 24 | 0.667 | 0.958 | 0.958 | 0.793 | 0.778 |
| fact | 60 | 0.567 | 0.800 | 0.850 | 0.661 | 0.697 |
| interaction | 19 | 0.526 | 0.737 | 0.947 | 0.635 | 0.675 |
| recommendation | 64 | 0.578 | 0.844 | 0.906 | 0.692 | 0.694 |

## Missed at 10 (23)

- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0065: (diabetes, pmc) Did severe hypoglycaemia occur with liraglutide in patients who were not taking a sulfonylurea?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0074: (diabetes, who) How often do sulfonylureas cause hypoglycaemia in patients without kidney problems?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0082: (diabetes, who) Which people with type 2 diabetes should be offered a statin under WHO PEN?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0102: (anticoagulation, pmc) By how much do strong CYP3A4 and P-glycoprotein inhibitors such as ketoconazole raise rivaroxaban levels?
- g0114: (anticoagulation, pmc) What is the standard edoxaban dose for atrial fibrillation?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0143: (respiratory, pmc) Which reliever inhaler did GINA 2019 and NAEPP 2020 recommend in place of salbutamol alone?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
