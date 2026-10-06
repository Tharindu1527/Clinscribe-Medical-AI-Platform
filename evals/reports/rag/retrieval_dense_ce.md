# Retrieval evaluation: `dense_ce`

Run 2026-10-06T09:48:40+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.440 | 0.713 | 0.828 | 0.563 | 0.598 |

Query latency (embed + search, warm, n=235): p50 2750 ms, p95 3912 ms.

Median top-1 similarity: answerable 4.613, unanswerable 1.851 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.425 | 0.675 | 0.850 | 0.549 | 0.601 |
| diabetes | 40 | 0.350 | 0.675 | 0.775 | 0.486 | 0.540 |
| hypertension | 43 | 0.512 | 0.767 | 0.837 | 0.631 | 0.641 |
| infections | 44 | 0.409 | 0.705 | 0.864 | 0.549 | 0.574 |
| respiratory | 42 | 0.500 | 0.738 | 0.810 | 0.592 | 0.631 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.469 | 0.778 | 0.852 | 0.603 | 0.630 |
| pmc | 85 | 0.447 | 0.706 | 0.824 | 0.561 | 0.612 |
| who | 43 | 0.372 | 0.605 | 0.791 | 0.489 | 0.511 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.500 | 0.773 | 0.773 | 0.592 | 0.561 |
| contraindication | 20 | 0.500 | 0.700 | 0.700 | 0.592 | 0.617 |
| dose | 24 | 0.458 | 0.875 | 1.000 | 0.670 | 0.691 |
| fact | 60 | 0.467 | 0.667 | 0.800 | 0.556 | 0.600 |
| interaction | 19 | 0.316 | 0.737 | 0.895 | 0.518 | 0.588 |
| recommendation | 64 | 0.406 | 0.672 | 0.828 | 0.523 | 0.571 |

## Missed at 10 (36)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0025: (hypertension, pmc) Should an ACE inhibitor be combined with an ARB in a hypertensive patient with kidney disease?
- g0026: (hypertension, pmc) After an ACE inhibitor or thiazide is started in the emergency department, when should electrolytes be checked?
- g0031: (hypertension, pmc) What blood pressure should be kept to prevent a first stroke?
- g0034: (hypertension, who) How common is secondary hypertension among people diagnosed with hypertension?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0068: (diabetes, pmc) In which situations is insulin considered for a person with type 2 diabetes?
- g0074: (diabetes, who) How often do sulfonylureas cause hypoglycaemia in patients without kidney problems?
- g0075: (diabetes, who) Do sulfonylureas cause more severe hypoglycaemia than DPP-4 or SGLT-2 inhibitors?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0133: (respiratory, openfda) What tendon risk arises when prednisone is taken with ciprofloxacin or levofloxacin?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0136: (respiratory, openfda) What is the immediate treatment if salmeterol triggers paradoxical bronchospasm?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0154: (respiratory, pmc) What does GINA recommend as first-line asthma treatment?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
