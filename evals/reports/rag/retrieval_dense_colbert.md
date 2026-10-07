# Retrieval evaluation: `dense_colbert`

Run 2026-10-06T10:14:30+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.478 | 0.785 | 0.852 | 0.609 | 0.628 |

Query latency (embed + search, warm, n=235): p50 132 ms, p95 178 ms.

Median top-1 similarity: answerable 30.841, unanswerable 30.299 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.475 | 0.750 | 0.825 | 0.582 | 0.616 |
| diabetes | 40 | 0.400 | 0.750 | 0.825 | 0.550 | 0.594 |
| hypertension | 43 | 0.512 | 0.884 | 0.907 | 0.660 | 0.668 |
| infections | 44 | 0.409 | 0.818 | 0.864 | 0.599 | 0.606 |
| respiratory | 42 | 0.595 | 0.714 | 0.833 | 0.651 | 0.652 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.531 | 0.802 | 0.864 | 0.657 | 0.657 |
| pmc | 85 | 0.447 | 0.776 | 0.859 | 0.581 | 0.623 |
| who | 43 | 0.442 | 0.767 | 0.814 | 0.574 | 0.583 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.455 | 0.818 | 0.909 | 0.628 | 0.611 |
| contraindication | 20 | 0.550 | 0.700 | 0.750 | 0.609 | 0.624 |
| dose | 24 | 0.583 | 0.958 | 1.000 | 0.747 | 0.736 |
| fact | 60 | 0.433 | 0.717 | 0.750 | 0.538 | 0.573 |
| interaction | 19 | 0.526 | 0.842 | 0.895 | 0.666 | 0.698 |
| recommendation | 64 | 0.453 | 0.781 | 0.891 | 0.602 | 0.624 |

## Missed at 10 (31)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0025: (hypertension, pmc) Should an ACE inhibitor be combined with an ARB in a hypertensive patient with kidney disease?
- g0034: (hypertension, who) How common is secondary hypertension among people diagnosed with hypertension?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
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
- g0110: (anticoagulation, pmc) Which DOAC is reported to be the safest choice in AF with severe kidney disease?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0133: (respiratory, openfda) What tendon risk arises when prednisone is taken with ciprofloxacin or levofloxacin?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0161: (respiratory, who) How does the WHO PEN package use peak flow to tell asthma from COPD?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
