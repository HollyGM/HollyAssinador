# Histórico de versões

## 0.2.0 — 2026-11-16

### Correções

- **Gravação segura do PDF assinado.** O arquivo de saída era aberto e zerado antes de assinar. Se a assinatura falhasse no meio (TSA fora do ar, token desconectado), um `-assinado.pdf` que já existisse era apagado. Agora o PDF é gravado num arquivo temporário e só substitui o destino no fim.
- **Original protegido de nomes parecidos.** Uma saída com o mesmo nome do original mudando só maiúsculas ou minúsculas ("Contrato.pdf" e "contrato.pdf", que no Mac são o mesmo arquivo) destruía o original, e o app ainda dizia "sucesso". Agora é recusada.
- **Certificado vencido não assina mais.** Antes, a assinatura saía sem aviso e seria rejeitada pelos validadores. O app também avisa quando faltam menos de 30 dias para o vencimento.

### Ajustes

- O carimbo visível mostra o nome do titular **sem o CPF/CNPJ** que o padrão ICP-Brasil põe no nome do certificado.
- A senha do A1 e o PIN do A3 são apagados do campo a cada assinatura, inclusive quando ela falha.
- Pergunta antes de substituir um PDF assinado que já existe, exceto quando o nome foi escolhido em "Salvar como…", que já pergunta.
- Mensagens de erro em português e específicas:
  - PIN incorreto, PIN bloqueado, PIN expirado, token ausente e token desconectado;
  - TSA fora do ar;
  - PDF protegido por senha, PDF corrompido e falta de permissão na pasta.

### Novidades

- **Assinatura em lote:** vários PDFs de uma vez, com o PIN do A3 digitado uma vez só. Cada PDF é salvo ao lado do original ou numa pasta escolhida. Um PDF com problema não interrompe os demais.
- Botão **Mostrar no Finder**, que abre a pasta com o PDF assinado selecionado.
- Testes automáticos (`tests/`) e verificação no GitHub a cada envio.

## 0.1.0 — 2026-10-09

- Primeira versão: assinatura PAdES com A1 (`.p12`/`.pfx`) ou A3 (PKCS#11), invisível ou com carimbo no rodapé em área livre, carimbo do tempo opcional e autoteste no pacote.
