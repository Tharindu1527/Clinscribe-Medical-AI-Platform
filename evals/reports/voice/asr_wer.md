# Medical speech recognition: Deepgram on PriMock57 (Phase 4)

6 PriMock57 consultations (CC BY 4.0), doctor and patient channels separately (7,686 reference words after normalisation). Keyterms: 98 (corpus drug list + general clinical words, not taken from these transcripts).

| configuration | WER all | WER doctor | WER patient | medical-term error rate |
|---|---|---|---|---|
| nova-3 | 0.119 | 0.111 | 0.132 | 0.090 (18/200) |
| nova-3 + keyterms | 0.121 | 0.112 | 0.135 | 0.085 (17/200) |
| nova-3-medical | 0.112 | 0.105 | 0.123 | 0.060 (12/200) |

Normalisation: lowercase, punctuation and transcript tags removed, filler words (um, uh,
erm ...) dropped from reference and hypothesis. Medical terms: single-word RxNorm lexicon
entries (5+ letters) and a fixed list of clinical words. No AssemblyAI comparison (no key).

| file | words | nova-3 | nova-3 + keyterms | nova-3-medical |
|---|---|---|---|---|
| day1_consultation01_doctor | 880 | 0.100 | 0.099 | 0.094 |
| day1_consultation01_patient | 438 | 0.089 | 0.089 | 0.075 |
| day1_consultation05_doctor | 957 | 0.156 | 0.160 | 0.147 |
| day1_consultation05_patient | 574 | 0.103 | 0.113 | 0.092 |
| day2_consultation03_doctor | 797 | 0.139 | 0.138 | 0.137 |
| day2_consultation03_patient | 550 | 0.169 | 0.165 | 0.153 |
| day3_consultation02_doctor | 750 | 0.104 | 0.104 | 0.104 |
| day3_consultation02_patient | 340 | 0.159 | 0.159 | 0.156 |
| day4_consultation04_doctor | 560 | 0.073 | 0.079 | 0.062 |
| day4_consultation04_patient | 381 | 0.136 | 0.136 | 0.129 |
| day5_consultation06_doctor | 807 | 0.076 | 0.073 | 0.067 |
| day5_consultation06_patient | 652 | 0.140 | 0.146 | 0.138 |
