# Retrieval evaluation: `dense_ctx`

Run 2026-10-06T15:18:41+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `4892616568b8` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.469 | 0.746 | 0.842 | 0.592 | 0.623 |

Query latency (embed + search, warm, n=235): p50 83 ms, p95 99 ms.

Median top-1 similarity: answerable 0.695, unanswerable 0.601 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.400 | 0.625 | 0.800 | 0.522 | 0.567 |
| diabetes | 40 | 0.325 | 0.675 | 0.800 | 0.465 | 0.488 |
| hypertension | 43 | 0.512 | 0.884 | 0.907 | 0.663 | 0.713 |
| infections | 44 | 0.545 | 0.818 | 0.886 | 0.672 | 0.698 |
| respiratory | 42 | 0.548 | 0.714 | 0.810 | 0.622 | 0.634 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.543 | 0.778 | 0.852 | 0.648 | 0.658 |
| pmc | 85 | 0.435 | 0.741 | 0.847 | 0.579 | 0.628 |
| who | 43 | 0.395 | 0.698 | 0.814 | 0.512 | 0.548 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.409 | 0.545 | 0.773 | 0.490 | 0.521 |
| contraindication | 20 | 0.400 | 0.750 | 0.800 | 0.547 | 0.574 |
| dose | 24 | 0.500 | 0.833 | 0.958 | 0.666 | 0.695 |
| fact | 60 | 0.417 | 0.767 | 0.817 | 0.555 | 0.611 |
| interaction | 19 | 0.526 | 0.737 | 0.947 | 0.641 | 0.682 |
| recommendation | 64 | 0.531 | 0.766 | 0.828 | 0.633 | 0.641 |

## Missed at 10 (33)

- g0025: (hypertension, pmc) Should an ACE inhibitor be combined with an ARB in a hypertensive patient with kidney disease?
- g0036: (hypertension, who) For which patients does WHO suggest choosing a diuretic or a calcium channel blocker first?
- g0039: (hypertension, who) In the WHO algorithm that does not use a single-pill combination, what is the first drug and dose?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0046: (diabetes, openfda) Is a small rise in creatinine expected after an SGLT2 inhibitor is started?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0065: (diabetes, pmc) Did severe hypoglycaemia occur with liraglutide in patients who were not taking a sulfonylurea?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0078: (diabetes, who) What does WHO advise adding when metformin alone does not control type 2 diabetes?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0108: (anticoagulation, pmc) Should a frail older person who is stable on warfarin be switched to a DOAC?
- g0116: (anticoagulation, pmc) Which DOAC has repeated reports of life-threatening bleeding during acute kidney injury?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0136: (respiratory, openfda) What is the immediate treatment if salmeterol triggers paradoxical bronchospasm?
- g0143: (respiratory, pmc) Which reliever inhaler did GINA 2019 and NAEPP 2020 recommend in place of salbutamol alone?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0154: (respiratory, pmc) What does GINA recommend as first-line asthma treatment?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0178: (infections, openfda) How long after an antibiotic course can C. difficile diarrhoea still appear?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
