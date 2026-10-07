# Retrieval evaluation: `bm25_ctx`

Run 2026-10-06T13:42:12+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `4892616568b8`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.411 | 0.703 | 0.799 | 0.533 | 0.576 |

Query latency (embed + search, warm, n=235): p50 1 ms, p95 1 ms.

Median top-1 similarity: answerable 22.866, unanswerable 14.978 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.400 | 0.650 | 0.725 | 0.490 | 0.533 |
| diabetes | 40 | 0.400 | 0.725 | 0.875 | 0.543 | 0.588 |
| hypertension | 43 | 0.465 | 0.767 | 0.860 | 0.590 | 0.632 |
| infections | 44 | 0.273 | 0.636 | 0.705 | 0.407 | 0.459 |
| respiratory | 42 | 0.524 | 0.738 | 0.833 | 0.639 | 0.673 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.395 | 0.716 | 0.815 | 0.531 | 0.570 |
| pmc | 85 | 0.435 | 0.694 | 0.776 | 0.537 | 0.583 |
| who | 43 | 0.395 | 0.698 | 0.814 | 0.528 | 0.574 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.318 | 0.636 | 0.773 | 0.465 | 0.529 |
| contraindication | 20 | 0.400 | 0.750 | 0.800 | 0.545 | 0.583 |
| dose | 24 | 0.458 | 0.792 | 0.833 | 0.594 | 0.622 |
| fact | 60 | 0.500 | 0.733 | 0.817 | 0.599 | 0.647 |
| interaction | 19 | 0.421 | 0.737 | 0.842 | 0.543 | 0.615 |
| recommendation | 64 | 0.344 | 0.641 | 0.766 | 0.465 | 0.495 |

## Missed at 10 (42)

- g0021: (hypertension, pmc) Which condition is now thought to be the most common cause of secondary hypertension?
- g0024: (hypertension, pmc) What blood pressure goal is suggested for a hypertensive patient with chronic kidney disease and albuminuria?
- g0031: (hypertension, pmc) What blood pressure should be kept to prevent a first stroke?
- g0036: (hypertension, who) For which patients does WHO suggest choosing a diuretic or a calcium channel blocker first?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0052: (diabetes, openfda) When should glipizide be taken relative to food?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0068: (diabetes, pmc) In which situations is insulin considered for a person with type 2 diabetes?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0099: (anticoagulation, openfda) Which patients should be started on lower warfarin doses?
- g0101: (anticoagulation, pmc) Does taking rivaroxaban with food change how much is absorbed?
- g0106: (anticoagulation, pmc) Which antibiotics are better choices for a urinary infection in someone taking warfarin?
- g0112: (anticoagulation, pmc) When should apixaban for atrial fibrillation be reduced to 2.5 mg twice daily?
- g0114: (anticoagulation, pmc) What is the standard edoxaban dose for atrial fibrillation?
- g0118: (anticoagulation, pmc) How much do DOAC blood levels vary from one patient to another?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0125: (respiratory, openfda) For which ages has nebulised budesonide been shown to be safe and effective?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0140: (respiratory, pmc) For which children is montelukast the preferred single controller medicine?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0171: (infections, openfda) What problem has been reported when older patients take co-trimoxazole with an ACE inhibitor?
- g0178: (infections, openfda) How long after an antibiotic course can C. difficile diarrhoea still appear?
- g0179: (infections, openfda) What are the most frequent side effects of levofloxacin?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0187: (infections, pmc) What can be given to a child with pneumonia who is allergic to penicillin?
- g0188: (infections, pmc) When does a child with pneumonia need intravenous antibiotics?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0194: (infections, pmc) For which respiratory diagnosis are antibiotics most often given inappropriately?
- g0200: (infections, who) What oral treatment does WHO suggest for an adult with pyelonephritis who is not vomiting?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
- g0208: (infections, who) Do white cells in the urine need antibiotics if the patient has no symptoms?
- g0209: (infections, who) Do most swollen lymph nodes need antibiotics?
