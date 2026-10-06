# Retrieval evaluation: `bm25`

Run 2026-10-06T09:15:34+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.325 | 0.593 | 0.699 | 0.441 | 0.481 |

Query latency (embed + search, warm, n=235): p50 1 ms, p95 1 ms.

Median top-1 similarity: answerable 21.756, unanswerable 15.240 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.325 | 0.500 | 0.625 | 0.411 | 0.448 |
| diabetes | 40 | 0.275 | 0.625 | 0.775 | 0.432 | 0.499 |
| hypertension | 43 | 0.326 | 0.674 | 0.721 | 0.457 | 0.496 |
| infections | 44 | 0.273 | 0.523 | 0.614 | 0.380 | 0.412 |
| respiratory | 42 | 0.429 | 0.643 | 0.762 | 0.525 | 0.553 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.358 | 0.654 | 0.741 | 0.480 | 0.513 |
| pmc | 85 | 0.318 | 0.529 | 0.659 | 0.416 | 0.462 |
| who | 43 | 0.279 | 0.605 | 0.698 | 0.417 | 0.462 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.273 | 0.636 | 0.682 | 0.417 | 0.477 |
| contraindication | 20 | 0.250 | 0.550 | 0.650 | 0.401 | 0.458 |
| dose | 24 | 0.458 | 0.833 | 0.875 | 0.601 | 0.624 |
| fact | 60 | 0.350 | 0.583 | 0.683 | 0.457 | 0.500 |
| interaction | 19 | 0.421 | 0.684 | 0.842 | 0.523 | 0.587 |
| recommendation | 64 | 0.266 | 0.484 | 0.625 | 0.363 | 0.388 |

## Missed at 10 (63)

- g0012: (hypertension, openfda) Can a mother keep breastfeeding while she takes lisinopril?
- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0017: (hypertension, pmc) What should be done about NSAIDs in a patient whose hypertension is resistant to treatment?
- g0019: (hypertension, pmc) During the acute phase of an ischaemic stroke, when should blood pressure drugs be started?
- g0020: (hypertension, pmc) At what age should screening for high blood pressure begin in adults?
- g0021: (hypertension, pmc) Which condition is now thought to be the most common cause of secondary hypertension?
- g0024: (hypertension, pmc) What blood pressure goal is suggested for a hypertensive patient with chronic kidney disease and albuminuria?
- g0029: (hypertension, pmc) An emergency patient has a reading of 185/115 but no sign of organ damage. Does the pressure need to be brought down quickly?
- g0031: (hypertension, pmc) What blood pressure should be kept to prevent a first stroke?
- g0036: (hypertension, who) For which patients does WHO suggest choosing a diuretic or a calcium channel blocker first?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0052: (diabetes, openfda) When should glipizide be taken relative to food?
- g0053: (diabetes, openfda) Which serious pancreatic problem has been reported after liraglutide came to market?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0058: (diabetes, openfda) What are the most frequent side effects of extended-release metformin?
- g0061: (diabetes, pmc) When should a GLP-1 receptor agonist be added for type 2 diabetes?
- g0068: (diabetes, pmc) In which situations is insulin considered for a person with type 2 diabetes?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0092: (anticoagulation, openfda) What eye checks are advised while a patient takes amiodarone?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0099: (anticoagulation, openfda) Which patients should be started on lower warfarin doses?
- g0101: (anticoagulation, pmc) Does taking rivaroxaban with food change how much is absorbed?
- g0106: (anticoagulation, pmc) Which antibiotics are better choices for a urinary infection in someone taking warfarin?
- g0110: (anticoagulation, pmc) Which DOAC is reported to be the safest choice in AF with severe kidney disease?
- g0112: (anticoagulation, pmc) When should apixaban for atrial fibrillation be reduced to 2.5 mg twice daily?
- g0114: (anticoagulation, pmc) What is the standard edoxaban dose for atrial fibrillation?
- g0117: (anticoagulation, pmc) Do very brief device-detected AF episodes raise the risk of stroke?
- g0118: (anticoagulation, pmc) How much do DOAC blood levels vary from one patient to another?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0125: (respiratory, openfda) For which ages has nebulised budesonide been shown to be safe and effective?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0140: (respiratory, pmc) For which children is montelukast the preferred single controller medicine?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0161: (respiratory, who) How does the WHO PEN package use peak flow to tell asthma from COPD?
- g0162: (respiratory, who) Which medicines should people with asthma avoid according to WHO PEN?
- g0163: (respiratory, who) When should a person with asthma be referred to a specialist under WHO PEN?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0171: (infections, openfda) What problem has been reported when older patients take co-trimoxazole with an ACE inhibitor?
- g0178: (infections, openfda) How long after an antibiotic course can C. difficile diarrhoea still appear?
- g0179: (infections, openfda) What are the most frequent side effects of levofloxacin?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0186: (infections, pmc) What is the first-line antibiotic for a child with non-severe pneumonia?
- g0187: (infections, pmc) What can be given to a child with pneumonia who is allergic to penicillin?
- g0188: (infections, pmc) When does a child with pneumonia need intravenous antibiotics?
- g0189: (infections, pmc) Which age group of children received the most antibiotics in Italian primary care?
- g0190: (infections, pmc) What does NICE recommend first for a urinary tract infection in pregnancy?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0194: (infections, pmc) For which respiratory diagnosis are antibiotics most often given inappropriately?
- g0201: (infections, who) How soon should a patient with an upper urinary infection improve after starting antibiotics?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
- g0208: (infections, who) Do white cells in the urine need antibiotics if the patient has no symptoms?
- g0209: (infections, who) Do most swollen lymph nodes need antibiotics?
