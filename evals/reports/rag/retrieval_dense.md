# Retrieval evaluation: `dense`

Run 2026-10-13T15:15:27+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.435 | 0.722 | 0.809 | 0.562 | 0.583 |

Query latency (embed + search, warm, n=235): p50 106 ms, p95 143 ms.

Median top-1 similarity: answerable 0.694, unanswerable 0.582 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.500 | 0.675 | 0.800 | 0.583 | 0.604 |
| diabetes | 40 | 0.375 | 0.600 | 0.750 | 0.467 | 0.494 |
| hypertension | 43 | 0.488 | 0.884 | 0.930 | 0.652 | 0.674 |
| infections | 44 | 0.364 | 0.773 | 0.864 | 0.556 | 0.591 |
| respiratory | 42 | 0.452 | 0.667 | 0.690 | 0.546 | 0.546 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.444 | 0.716 | 0.778 | 0.572 | 0.572 |
| pmc | 85 | 0.482 | 0.765 | 0.859 | 0.605 | 0.637 |
| who | 43 | 0.326 | 0.651 | 0.767 | 0.458 | 0.496 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.318 | 0.682 | 0.773 | 0.469 | 0.497 |
| contraindication | 20 | 0.450 | 0.650 | 0.700 | 0.515 | 0.521 |
| dose | 24 | 0.417 | 0.958 | 0.958 | 0.654 | 0.662 |
| fact | 60 | 0.400 | 0.683 | 0.783 | 0.529 | 0.578 |
| interaction | 19 | 0.474 | 0.737 | 0.789 | 0.595 | 0.609 |
| recommendation | 64 | 0.500 | 0.703 | 0.828 | 0.594 | 0.599 |

## Missed at 10 (40)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0025: (hypertension, pmc) Should an ACE inhibitor be combined with an ARB in a hypertensive patient with kidney disease?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0046: (diabetes, openfda) Is a small rise in creatinine expected after an SGLT2 inhibitor is started?
- g0047: (diabetes, openfda) Can empagliflozin be used purely for glucose control when the eGFR is under 30?
- g0050: (diabetes, openfda) A patient on a sulfonylurea is starting semaglutide. Should anything be changed?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0078: (diabetes, who) What does WHO advise adding when metformin alone does not control type 2 diabetes?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0082: (diabetes, who) Which people with type 2 diabetes should be offered a statin under WHO PEN?
- g0084: (anticoagulation, openfda) Can dabigatran be given together with a P-gp inhibitor when creatinine clearance is 15 to 30?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0133: (respiratory, openfda) What tendon risk arises when prednisone is taken with ciprofloxacin or levofloxacin?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0136: (respiratory, openfda) What is the immediate treatment if salmeterol triggers paradoxical bronchospasm?
- g0143: (respiratory, pmc) Which reliever inhaler did GINA 2019 and NAEPP 2020 recommend in place of salbutamol alone?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0154: (respiratory, pmc) What does GINA recommend as first-line asthma treatment?
- g0162: (respiratory, who) Which medicines should people with asthma avoid according to WHO PEN?
- g0163: (respiratory, who) When should a person with asthma be referred to a specialist under WHO PEN?
- g0164: (respiratory, who) At the top step of WHO PEN asthma care, how much oral prednisolone is normally used?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
