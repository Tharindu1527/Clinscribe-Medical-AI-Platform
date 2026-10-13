# Retrieval evaluation: `hybrid`

Run 2026-10-13T15:16:19+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.407 | 0.679 | 0.813 | 0.533 | 0.571 |

Query latency (embed + search, warm, n=235): p50 106 ms, p95 133 ms.

Median top-1 similarity: answerable 0.032, unanswerable 0.031 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.475 | 0.650 | 0.750 | 0.548 | 0.572 |
| diabetes | 40 | 0.325 | 0.700 | 0.800 | 0.487 | 0.552 |
| hypertension | 43 | 0.349 | 0.791 | 0.907 | 0.551 | 0.610 |
| infections | 44 | 0.364 | 0.591 | 0.795 | 0.486 | 0.497 |
| respiratory | 42 | 0.524 | 0.667 | 0.810 | 0.596 | 0.623 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.407 | 0.728 | 0.802 | 0.556 | 0.579 |
| pmc | 85 | 0.447 | 0.635 | 0.812 | 0.533 | 0.579 |
| who | 43 | 0.326 | 0.674 | 0.837 | 0.492 | 0.539 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.364 | 0.682 | 0.773 | 0.507 | 0.535 |
| contraindication | 20 | 0.400 | 0.650 | 0.750 | 0.503 | 0.550 |
| dose | 24 | 0.542 | 0.958 | 1.000 | 0.721 | 0.726 |
| fact | 60 | 0.367 | 0.600 | 0.733 | 0.485 | 0.537 |
| interaction | 19 | 0.421 | 0.737 | 0.789 | 0.575 | 0.610 |
| recommendation | 64 | 0.406 | 0.641 | 0.859 | 0.515 | 0.550 |

## Missed at 10 (39)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0021: (hypertension, pmc) Which condition is now thought to be the most common cause of secondary hypertension?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0053: (diabetes, openfda) Which serious pancreatic problem has been reported after liraglutide came to market?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0068: (diabetes, pmc) In which situations is insulin considered for a person with type 2 diabetes?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0082: (diabetes, who) Which people with type 2 diabetes should be offered a statin under WHO PEN?
- g0084: (anticoagulation, openfda) Can dabigatran be given together with a P-gp inhibitor when creatinine clearance is 15 to 30?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0101: (anticoagulation, pmc) Does taking rivaroxaban with food change how much is absorbed?
- g0118: (anticoagulation, pmc) How much do DOAC blood levels vary from one patient to another?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0133: (respiratory, openfda) What tendon risk arises when prednisone is taken with ciprofloxacin or levofloxacin?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0140: (respiratory, pmc) For which children is montelukast the preferred single controller medicine?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0161: (respiratory, who) How does the WHO PEN package use peak flow to tell asthma from COPD?
- g0171: (infections, openfda) What problem has been reported when older patients take co-trimoxazole with an ACE inhibitor?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0187: (infections, pmc) What can be given to a child with pneumonia who is allergic to penicillin?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0194: (infections, pmc) For which respiratory diagnosis are antibiotics most often given inappropriately?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
