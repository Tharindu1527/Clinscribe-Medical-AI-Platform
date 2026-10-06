# Retrieval evaluation: `hybrid_ctx`

Run 2026-10-06T15:19:24+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `4892616568b8` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.512 | 0.756 | 0.847 | 0.617 | 0.643 |

Query latency (embed + search, warm, n=235): p50 96 ms, p95 120 ms.

Median top-1 similarity: answerable 0.033, unanswerable 0.031 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.525 | 0.625 | 0.775 | 0.593 | 0.608 |
| diabetes | 40 | 0.450 | 0.800 | 0.850 | 0.579 | 0.610 |
| hypertension | 43 | 0.581 | 0.837 | 0.907 | 0.699 | 0.727 |
| infections | 44 | 0.409 | 0.727 | 0.864 | 0.552 | 0.585 |
| respiratory | 42 | 0.595 | 0.786 | 0.833 | 0.661 | 0.684 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.506 | 0.802 | 0.852 | 0.625 | 0.649 |
| pmc | 85 | 0.565 | 0.706 | 0.835 | 0.642 | 0.664 |
| who | 43 | 0.419 | 0.767 | 0.860 | 0.553 | 0.590 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.455 | 0.773 | 0.773 | 0.525 | 0.557 |
| contraindication | 20 | 0.600 | 0.750 | 0.800 | 0.674 | 0.671 |
| dose | 24 | 0.458 | 0.833 | 1.000 | 0.641 | 0.691 |
| fact | 60 | 0.517 | 0.717 | 0.817 | 0.623 | 0.663 |
| interaction | 19 | 0.474 | 0.789 | 0.895 | 0.612 | 0.675 |
| recommendation | 64 | 0.531 | 0.750 | 0.844 | 0.617 | 0.619 |

## Missed at 10 (32)

- g0031: (hypertension, pmc) What blood pressure should be kept to prevent a first stroke?
- g0036: (hypertension, who) For which patients does WHO suggest choosing a diuretic or a calcium channel blocker first?
- g0040: (hypertension, who) Can ACE inhibitors or ARBs be used to treat hypertension in a pregnant woman?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0065: (diabetes, pmc) Did severe hypoglycaemia occur with liraglutide in patients who were not taking a sulfonylurea?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0101: (anticoagulation, pmc) Does taking rivaroxaban with food change how much is absorbed?
- g0106: (anticoagulation, pmc) Which antibiotics are better choices for a urinary infection in someone taking warfarin?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0140: (respiratory, pmc) For which children is montelukast the preferred single controller medicine?
- g0143: (respiratory, pmc) Which reliever inhaler did GINA 2019 and NAEPP 2020 recommend in place of salbutamol alone?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0178: (infections, openfda) How long after an antibiotic course can C. difficile diarrhoea still appear?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0187: (infections, pmc) What can be given to a child with pneumonia who is allergic to penicillin?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0194: (infections, pmc) For which respiratory diagnosis are antibiotics most often given inappropriately?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
