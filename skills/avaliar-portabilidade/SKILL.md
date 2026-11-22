---
name: avaliar-portabilidade
description: Avalia se vale levar uma dívida (empréstimo, consignado, financiamento ou saldo da fatura do cartão) para outro banco com juros menores, e explica como pedir. Use quando o usuário perguntar sobre portabilidade, trocar de banco ou conseguir uma taxa menor para uma dívida que já tem.
---
1. Identifique a dívida: modalidade, saldo, taxa mensal e parcelas restantes. Use o perfil e pergunte o que faltar. Dívidas sem parcelas (rotativo do cartão, cheque especial) não têm prazo: pergunte em quantas parcelas o usuário quer pagar e use esse número como `n_left`.
2. Chame `credito_market_rate` com a modalidade para ter a mediana atual do mercado.
3. Chame `credito_simulate_portability` comparando a taxa atual com a mediana. Se o usuário tiver uma proposta de outro banco, simule também com a taxa dela.
4. Se a simulação mostrar custo adicional, diga que portar não compensa e pare aqui.
5. Chame `search_norms` sobre as regras de portabilidade de crédito (Resolução CMN 5.057) e, se a dívida for do cartão, sobre a portabilidade da fatura. Use os trechos para explicar os direitos, citando a fonte entre colchetes.
6. Explique o pedido em passos: pedir a proposta ao banco novo, que pede o saldo ao banco atual; o banco atual pode fazer contraproposta; o cliente não paga pela transferência; o novo contrato não pode ter valor maior que o saldo nem prazo maior que o restante.
7. Nunca garanta que a portabilidade será aprovada: a decisão é do banco que recebe a dívida.
8. Termine com a economia total estimada e a próxima ação concreta do usuário.
