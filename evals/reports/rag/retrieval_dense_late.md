# Retrieval evaluation: `dense_late`

Run 2026-10-07T15:45:50+00:00 · golden set `9a9e231f27e0` (209 answerable questions) · corpus `78f6c54b780b` · model `nomic-ai/modernbert-embed-base` @ `d556a88e3325`

Recall@k is answer-level: a question counts as found when any chunk containing its quoted
answer is in the top k. MRR@10 and nDCG@10 use every gold chunk (binary relevance).
Gold chunks are those containing the exact quote, so a chunk giving the same answer in
other words counts as a miss: these numbers are a lower bound for every system.

| set | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| all | 209 | 0.340 | 0.646 | 0.727 | 0.458 | 0.502 |

Query latency (embed + search, warm, n=235): p50 82 ms, p95 108 ms.

Median top-1 similarity: answerable 0.670, unanswerable 0.591 (a first look at whether a score threshold could support abstention; not used yet).

## By area

| area | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| anticoagulation | 40 | 0.225 | 0.575 | 0.650 | 0.341 | 0.407 |
| diabetes | 40 | 0.300 | 0.600 | 0.700 | 0.415 | 0.450 |
| hypertension | 43 | 0.465 | 0.814 | 0.907 | 0.612 | 0.653 |
| infections | 44 | 0.341 | 0.636 | 0.705 | 0.455 | 0.500 |
| respiratory | 42 | 0.357 | 0.595 | 0.667 | 0.456 | 0.491 |

## By source

| source | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| openfda | 81 | 0.346 | 0.691 | 0.716 | 0.481 | 0.528 |
| pmc | 85 | 0.365 | 0.635 | 0.729 | 0.464 | 0.513 |
| who | 43 | 0.279 | 0.581 | 0.744 | 0.402 | 0.434 |

## By qtype

| qtype | n | recall@1 | recall@5 | recall@10 | mrr@10 | ndcg@10 |
|---|---|---|---|---|---|---|
| adverse_effect | 22 | 0.364 | 0.545 | 0.591 | 0.438 | 0.453 |
| contraindication | 20 | 0.250 | 0.500 | 0.600 | 0.339 | 0.380 |
| dose | 24 | 0.375 | 0.875 | 0.958 | 0.562 | 0.613 |
| fact | 60 | 0.350 | 0.600 | 0.683 | 0.443 | 0.494 |
| interaction | 19 | 0.263 | 0.684 | 0.737 | 0.432 | 0.514 |
| recommendation | 64 | 0.359 | 0.672 | 0.766 | 0.485 | 0.521 |

## Missed at 10 (57)

- g0014: (hypertension, openfda) Which tablet strengths are available for valsartan?
- g0025: (hypertension, pmc) Should an ACE inhibitor be combined with an ARB in a hypertensive patient with kidney disease?
- g0034: (hypertension, who) How common is secondary hypertension among people diagnosed with hypertension?
- g0041: (hypertension, who) After a blood pressure medicine is started or increased, when should the pressure be measured again?
- g0046: (diabetes, openfda) Is a small rise in creatinine expected after an SGLT2 inhibitor is started?
- g0047: (diabetes, openfda) Can empagliflozin be used purely for glucose control when the eGFR is under 30?
- g0048: (diabetes, openfda) How often did genital fungal infections occur on empagliflozin compared with placebo?
- g0050: (diabetes, openfda) A patient on a sulfonylurea is starting semaglutide. Should anything be changed?
- g0054: (diabetes, openfda) What anaesthesia-related risk has been reported with GLP-1 drugs?
- g0055: (diabetes, openfda) Which drugs can hide the warning symptoms of low blood sugar in someone on insulin?
- g0056: (diabetes, openfda) Should a dose of insulin glargine be given while the patient is hypoglycaemic?
- g0061: (diabetes, pmc) When should a GLP-1 receptor agonist be added for type 2 diabetes?
- g0065: (diabetes, pmc) Did severe hypoglycaemia occur with liraglutide in patients who were not taking a sulfonylurea?
- g0066: (diabetes, pmc) Which adverse effects need to be kept in mind with SGLT2 inhibitors?
- g0067: (diabetes, pmc) How do SGLT2 inhibitors lower blood glucose?
- g0081: (diabetes, who) Which medicine is first-line for type 2 diabetes in the WHO PEN package?
- g0084: (anticoagulation, openfda) Can dabigatran be given together with a P-gp inhibitor when creatinine clearance is 15 to 30?
- g0085: (anticoagulation, openfda) Are DOACs suitable for a patient with triple-positive antiphospholipid syndrome?
- g0088: (anticoagulation, openfda) Can apixaban be used in a patient with severe liver impairment?
- g0089: (anticoagulation, openfda) Is anaemia more common with edoxaban than with warfarin?
- g0090: (anticoagulation, openfda) Can rivaroxaban be cleared by haemodialysis in an overdose?
- g0093: (anticoagulation, openfda) Is there a reversal agent for dabigatran?
- g0094: (anticoagulation, openfda) For how long does edoxaban keep anticoagulating after the final dose?
- g0095: (anticoagulation, openfda) Which antidepressant classes add to the bleeding risk of edoxaban?
- g0096: (anticoagulation, openfda) How long must initial DVT or PE treatment last before rivaroxaban is used to prevent recurrence?
- g0108: (anticoagulation, pmc) Should a frail older person who is stable on warfarin be switched to a DOAC?
- g0114: (anticoagulation, pmc) What is the standard edoxaban dose for atrial fibrillation?
- g0116: (anticoagulation, pmc) Which DOAC has repeated reports of life-threatening bleeding during acute kidney injury?
- g0120: (anticoagulation, pmc) An older patient with AF has fallen once without injury. Should the anticoagulant be stopped?
- g0121: (anticoagulation, pmc) Which anticoagulant was the standard for cancer-associated thrombosis before DOACs?
- g0127: (respiratory, openfda) In which men should tiotropium be used with care because of urinary problems?
- g0133: (respiratory, openfda) What tendon risk arises when prednisone is taken with ciprofloxacin or levofloxacin?
- g0135: (respiratory, openfda) Can someone using salmeterol also use a formoterol inhaler?
- g0136: (respiratory, openfda) What is the immediate treatment if salmeterol triggers paradoxical bronchospasm?
- g0141: (respiratory, pmc) Which side effects of montelukast are often seen in children?
- g0143: (respiratory, pmc) Which reliever inhaler did GINA 2019 and NAEPP 2020 recommend in place of salbutamol alone?
- g0146: (respiratory, pmc) What does an intermediate exhaled nitric oxide reading of 20 to 35 ppb mean?
- g0148: (respiratory, pmc) Which admission findings predict early failure of non-invasive ventilation in a COPD exacerbation?
- g0149: (respiratory, pmc) Is a short-acting beta-agonist on its own an acceptable asthma treatment?
- g0152: (respiratory, pmc) How common is NSAID-exacerbated respiratory disease in people with asthma?
- g0153: (respiratory, pmc) In chronic asthma, is adding a second controller better than raising the inhaled steroid dose?
- g0154: (respiratory, pmc) What does GINA recommend as first-line asthma treatment?
- g0162: (respiratory, who) Which medicines should people with asthma avoid according to WHO PEN?
- g0165: (respiratory, who) How quickly do inhaled steroids reach their full effect in asthma?
- g0178: (infections, openfda) How long after an antibiotic course can C. difficile diarrhoea still appear?
- g0182: (infections, openfda) Can amoxicillin stain the teeth?
- g0184: (infections, pmc) How often does childhood pneumonia lead to a pleural effusion or empyema?
- g0185: (infections, pmc) What was the strongest predictor of dying in hospital with healthcare-associated pneumonia?
- g0188: (infections, pmc) When does a child with pneumonia need intravenous antibiotics?
- g0190: (infections, pmc) What does NICE recommend first for a urinary tract infection in pregnancy?
- g0193: (infections, pmc) Did point-of-care CRP testing lower antibiotic use for chest infections?
- g0198: (infections, who) Which patients with asymptomatic bacteriuria may still need pre-emptive antibiotics?
- g0199: (infections, who) How often is a sore throat treated with antibiotics in high-income outpatient care?
- g0202: (infections, who) Which antibiotics does WHO recommend for a severe kidney infection with sepsis?
- g0203: (infections, who) In places where rheumatic fever is rare, does a high Centor score mean a sore throat needs antibiotics?
- g0204: (infections, who) By how much do antibiotics shorten sore throat pain?
- g0206: (infections, who) What most commonly causes community-acquired pneumonia worldwide?
