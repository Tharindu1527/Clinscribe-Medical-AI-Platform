# Retrieval evaluation: `hybrid_colbert_late`

Run 2026-10-13T15:30:58+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.464 | 0.785 | 0.861 | 0.599 | 0.627 |

Query latency (embed + search, warm, n=235): p50 166 ms, p95 235 ms.

Median top-1 similarity: answerable 30.838, unanswerable 30.300 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.450 | 0.750 | 0.825 | 0.568 | 0.612 |
| diabetes | 40 | 0.425 | 0.700 | 0.800 | 0.548 | 0.590 |
| hypertension | 43 | 0.512 | 0.884 | 0.907 | 0.662 | 0.674 |
| infections | 44 | 0.364 | 0.841 | 0.886 | 0.574 | 0.599 |
| respiratory | 42 | 0.571 | 0.738 | 0.881 | 0.638 | 0.658 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.506 | 0.790 | 0.840 | 0.635 | 0.643 |
| pmc | 85 | 0.447 | 0.788 | 0.918 | 0.589 | 0.646 |
| who | 43 | 0.419 | 0.767 | 0.791 | 0.550 | 0.559 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.455 | 0.727 | 0.818 | 0.582 | 0.591 |
| contraindication | 20 | 0.500 | 0.650 | 0.700 | 0.574 | 0.595 |
| dose | 24 | 0.583 | 1.000 | 1.000 | 0.741 | 0.743 |
| fact | 60 | 0.433 | 0.733 | 0.767 | 0.540 | 0.578 |
| interaction | 19 | 0.421 | 0.895 | 0.947 | 0.631 | 0.685 |
| recommendation | 64 | 0.453 | 0.781 | 0.938 | 0.605 | 0.635 |

## Missed at 10 (29)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0034: (hypertension, who) How common is secondary hypertension among people diagnosed with hypertension?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0061: (diabetes, pmc) When should a GLP-1 receptor agonist be added for type 2 diabetes?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0082: (diabetes, who) Which people with type 2 diabetes should be offered a statin under WHO PEN?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0161: (respiratory, who) How does the WHO PEN package use peak flow to tell asthma from COPD?
- g0162: (respiratory, who) Which medicines should people with asthma avoid according to WHO PEN?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
