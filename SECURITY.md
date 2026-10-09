# Segurança

## Chaves privadas

- A1: a chave é carregada apenas durante a operação de assinatura.
- A3: a chave privada permanece no token/cartão; o software solicita a operação
  criptográfica ao módulo PKCS#11.
- Senhas e PINs não são gravados em arquivo por este projeto.

## Recomendações de produção

- Não registrar senha, PIN, conteúdo de chave privada ou PKCS#12 em logs.
- Validar a cadeia ICP-Brasil de acordo com a política exigida pelo sistema.
- Configurar OCSP/CRL e TSA quando o perfil de assinatura exigir.
- Assinar e notarizar o aplicativo antes da distribuição.
- Para integração web/local, exigir autorização por origem e confirmação
  explícita do usuário para cada documento.
