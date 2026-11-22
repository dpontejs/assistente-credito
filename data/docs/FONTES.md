# Fontes do corpus normativo

Coleta: 22/11/2026, com `uv run python scripts/download_corpus.py`. A pesquisa que
escolheu as fontes, com vigência e alterações de cada norma, está resumida abaixo;
lei e norma não têm direito autoral (Lei 9.610/1998, art. 8º, IV), por isso os
textos limpos ficam versionados em `data/docs/<id>.txt`.

## Núcleo indexado

| id | Documento | Número | URL oficial | Como foi baixado | Vigência |
|---|---|---|---|---|---|
| `cdc` | Código de Defesa do Consumidor, só os artigos de crédito (6º, 39, 42, 42-A, 43, 51, 52, 54-A a 54-G, 104-A a 104-C) | Lei 8.078/1990 | https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm | Planalto, texto compilado | Vigente, com a Lei 14.181/2021 |
| `dec11150` | Mínimo existencial | Decreto 11.150/2022 | https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2022/decreto/d11150.htm | Planalto, consolidado | Vigente, com o Decreto 11.567/2023; ver nota do STF |
| `lei14690` | Desenrola: teto do rotativo e portabilidade da fatura (arts. 27 e 28) | Lei 14.690/2023 | https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/lei/l14690.htm | Planalto | Vigente |
| `lei10820` | Crédito consignado | Lei 10.820/2003 | https://www.planalto.gov.br/ccivil_03/leis/2003/L10.820compilado.htm | Planalto, compilado | Vigente; MP 1.355/2026 caducou |
| `res4549` | Rotativo e parcelamento da fatura | Resolução 4549 (CMN, 2017) | API do BCB, `p1=Resolução&p2=4549` | PDF consolidado `Res_4549_v2_L.pdf` | Vigente, com a CMN 5.112/2023 |
| `bcb96` | Contas de pagamento e fatura do cartão | Resolução BCB 96 (2021) | API do BCB, `p1=Resolução BCB&p2=96` | Texto consolidado da API | Vigente |
| `cmn4882` | Encargos por atraso | Resolução CMN 4882 (2020) | API do BCB, `p1=Resolução CMN&p2=4882` | Texto da API | Vigente |
| `res4765` | Cheque especial | Resolução 4765 (CMN, 2019) | API do BCB, `p1=Resolução&p2=4765` | PDF consolidado `Res_4765_v2_L.pdf` | Vigente; art. 2º revogado (ADI 6.407) |
| `cmn5057` | Portabilidade de crédito | Resolução CMN 5057 (2022) | API do BCB, `p1=Resolução CMN&p2=5057` | Texto consolidado da API | Vigente, com as CMN 5.112/2023 e 5.265/2025 |
| `res3919` | Tarifas bancárias | Resolução 3919 (CMN, 2010) | API do BCB, `p1=Resolução&p2=3919` | PDF consolidado `Res_3919_v7_L.pdf` | Vigente |
| `cmn4881` | Custo efetivo total (CET) | Resolução CMN 4881 (2020) | API do BCB, `p1=Resolução CMN&p2=4881` | Texto da API | Vigente |

API do BCB: `https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo?p1=<Tipo>&p2=<Número>`;
PDFs em `https://normativos.bcb.gov.br/Lists/Normativos/Attachments/<Id>/<arquivo>`.

## Notas curadas (`data/docs/notas/`)

Textos curtos escritos para o corpus porque os textos oficiais não refletem decisões
posteriores. Cada nota cita suas fontes no cabeçalho: mínimo existencial após o STF,
MP 1.355 caducada, cheque especial sem tarifa, teto de 100% do rotativo, "30 dias" do
rotativo, vigência da Lei 15.252, teto do consignado do INSS (CNPS 1.368/2025),
art. 54-E do CDC vetado e portabilidade da fatura.

## Fora do núcleo, por enquanto

Vigentes, mas só entram se algum caso de teste pedir: Lei 14.181/2021 (já absorvida
pelo CDC), Decreto 11.567/2023, Res. CMN 5.112/2023 (absorvida pela 4.549), Res. CMN
5.004/2022, Res. CMN 5.265/2025, Res. BCB 283/2023, Res. Conjunta 15/2025, Lei
15.179/2025, Lei 15.327/2026, Lei 8.213/1991 (art. 115), Res. CMN 4.949/2021, Res. CMN
5.037/2022, Lei 12.414/2011, Lei 15.252/2025 (coberta pela nota), Res. CMN 5.299/2026,
Decreto 13.135/2026, Res. 4.790/2020 e Res. CMN 5.058/2022 (ambas até 30/6/2027).

## Só a partir de 1º/7/2027

Res. BCB 564, 566 e 567/2026 (regulamentação da Lei 15.252). Res. BCB 601, 602 e
603/2026 com vigência não confirmada. Revisar o corpus nessa data.

## Revogadas (não indexar)

Res. CMN 4.292/2013 (portabilidade, substituída pela 5.057), Res. 4.655/2018 e
4.558/2017 (encargos de atraso, substituídas pela 4.882), Circular 3.512/2010 art. 1º
(pagamento mínimo de 15%), Circular 3.981/2020, Decreto 11.034/2022 (SAC, substituído
pelo 13.135), MP 1.355/2026 (caducou), MP 1.292/2025 (convertida na Lei 15.179) e
Res. CNPS 1.367/2025 (substituída pela 1.368).

## Verificações pendentes

Prazo máximo do consignado INSS, redação atual da Lei 14.509/2022 (servidores
federais), conteúdo das Res. 4.790/2020 e CMN 5.058/2022, Acórdão TCU 1094/2026 e
ADI 7.759 (vistos só em resultados de busca).
