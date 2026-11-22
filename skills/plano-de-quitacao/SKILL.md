---
name: plano-de-quitacao
description: Monta um plano de quitação das dívidas do usuário, com ordem de pagamento, prazos e cronograma com datas. Use quando o usuário pedir um plano para sair das dívidas, perguntar qual dívida pagar primeiro ou quanto tempo leva para quitar tudo.
---
1. Confira as dívidas e a renda no perfil do usuário. Se faltar a taxa ou o saldo de alguma dívida, pergunte antes de seguir.
2. Para cada dívida, chame `credito_compare_rate` com a modalidade e a taxa mensal, para saber se ela está acima ou abaixo da mediana do mercado.
3. Pergunte quanto o usuário consegue pagar por mês no total, se ele ainda não disse. Nunca proponha comprometer mais de 30% da renda sem ele pedir.
4. Ordene as dívidas pelo método avalanche (maior taxa primeiro). Use bola de neve (menor saldo primeiro) só se o usuário preferir; explique a diferença em uma frase.
5. Pague o mínimo nas demais dívidas e concentre a sobra na primeira da fila. Para cada dívida, chame `credito_simulate_payoff` com o valor que ela recebe por mês. Se a ferramenta disser que a parcela não cobre os juros, aumente o valor dessa dívida ou avise o usuário.
6. Dívidas acima da mediana do mercado: mencione que a portabilidade pode baratear (a skill avaliar-portabilidade detalha).
7. Chame `time_get_current_time` e transforme os meses de cada simulação em datas de quitação previstas.
8. Apresente o plano em uma lista: ordem, valor mensal de cada dívida, data prevista de quitação e juros totais. Termine com o total de juros do plano.
9. Pergunte se o usuário quer guardar o plano. Se ele aceitar, chame `credito_save_plan` com o plano em texto curto.
