# Aurora — portal nacional Django

Projeto novo, independente de qualquer site clonado. Interface própria roxa/rosa/coral, mobile-first, com Bootstrap 5 servido localmente. Sem fotos de terceiros, anunciantes fictícios publicados ou pagamentos simulados.

## Implementado

- Declaração de acesso 18+, cadastro, login com limitação de tentativas e painel por proprietário.
- Perfis nacionais com estado/cidade/bairro, idade adulta, descrição, contato autorizado, disponibilidade, filtros e paginação.
- Galerias por setas e gesto de deslizar; envio JPEG/PNG/WebP, conversão WebP, remoção de metadados, até 12 fotos, ordenação e exclusão.
- Publicação condicionada à identidade verificada, maioridade comprovada, fotos consentidas/aprovadas e revisão atual do perfil.
- Documentos criptografados com Fernet, permissão restrita para download, auditoria e revisão manual.
- Planos configuráveis, prioridade orgânica por atualização e publicidade por assinatura vigente; vencimento/revogação removem benefício imediatamente nas consultas.
- Checkout hospedado Mercado Pago e webhook com HMAC, consulta ao provedor, validação de valor/moeda/referência e assinatura idempotente.
- Pagamentos **desabilitados por padrão**. Retornar do checkout nunca ativa assinatura.
- Indicadores administrativos, denúncias, ocultação, solicitação de exclusão e comando de anonimização após revisão legal.
- Sitemap, robots e estatísticas agregadas sem registro de IP nos acessos.
- Home, perfis, login, cadastro, painel, planos e tabelas responsivos. Administração utiliza a interface responsiva do Django.

## Ubuntu

```bash
sudo apt update
sudo apt install python3 python3-venv postgresql make
cd /home/marcos/Documents/clone
make install
cp .env.example .env  # somente se ainda não existir; não sobrescreva sua configuração
chmod 600 .env
```

Configure banco, usuário, senha, hosts e segredo em `.env`. O arquivo é carregado automaticamente, ignorado pelo Git e não deve ser compartilhado. Use um usuário PostgreSQL exclusivo, não o administrador, em produção.

```bash
make migrate
make user
make web
```

Acesse http://127.0.0.1:8000. Confirme maioridade. Contas existentes no banco Django continuam utilizáveis. Cada conta inicia um perfil pelo painel; a home fica vazia até haver perfis genuínos aprovados.

No painel, preencha e salve **Meu perfil** antes de enviar fotos. O link **Minhas fotos** sempre abre a seção: sem perfil, ela explica o requisito; após salvar, mostra o formulário de envio, sem precisar aguardar aprovação. **Verificação** é uma seção separada para documentos e depende da chave de criptografia.

## Verificação e publicação

1. Gere uma chave Fernet e mantenha-a em segredo no ambiente (`IDENTITY_ENCRYPTION_KEY`). Não troque a chave sem migrar documentos já criptografados. Faça backup protegido da chave e dos documentos.
2. O anunciante envia documento legível (JPEG, PNG ou WebP) e confirma o consentimento.
3. Administrador com permissão específica revisa o documento em `/admin/moderacao/identitycheck/`, informa a data de nascimento e confirma identidade/maioridade.
4. Revise **cada foto**, a titularidade e consentimento de todas as pessoas retratadas antes de marcar fotos como aprovadas.
5. Em anunciantes, use a ação **Aprovar perfis**. Ausência de identidade/fotos aprovadas bloqueia publicação.
6. Edição de perfil ou galeria retorna para revisão. Perfis suspensos não podem se autopublicar.

Uma simples caixa de consentimento não comprova direitos de terceiros. O operador precisa manter procedimentos, evidências e uma equipe de moderação. Não há reconhecimento facial ou verificação automática de documento.

## Planos e pagamentos

Cadastre planos em `/admin/assinaturas/plan/`. Básico tem prioridade 0. Destaque/Premium têm prioridade positiva configurável. Preço/duração/benefício são congelados no pedido para evitar alteração de compras passadas.

Para habilitar, a categoria do portal deve ser **aprovada pelo Mercado Pago**. Configure HTTPS público, token de acesso, segredo de webhook, `PUBLIC_ORIGIN`, `PAYMENT_PROVIDER_APPROVED=1` e `PAYMENTS_ENABLED=1`. Use o ambiente de homologação do provedor primeiro.

O webhook é `/pagamentos/webhook/`, espera `data.id` na query, `data.id` no JSON, `x-signature` e `x-request-id`. Consulta `/v1/payments/<id>` no servidor do provedor antes de ativar. Confirmação duplicada não cria outra assinatura; reembolso/chargeback revoga benefícios. Renovações são novas compras confirmadas, sem débito recorrente automático.

**Integração real ainda não homologada com uma conta do provedor.** Os testes verificam a lógica com respostas de teste, não comprovam aprovação comercial. Não cadastre cartões ou cobranças reais antes da homologação. Reconciliação periódica, tratamento operacional de disputas e recorrência automática ainda precisam ser desenvolvidos antes de operação comercial.

## Privacidade e exclusão

`media/` e `private/` não devem ser servidos como diretórios públicos. Fotos passam pelo endpoint Django que verifica publicação/permissão. Documentos só são servidos via permissão `moderacao.view_identitycheck` e com cache desativado.

Uma solicitação de exclusão oculta o perfil imediatamente. Após revisar retenção legal:

```bash
.venv/bin/python manage.py complete_deletion ID_DA_SOLICITACAO --confirm-legal-review
```

O comando remove fotos/documento, anonimiza perfil/conta e conserva registros financeiros e auditoria para obrigações legais. Não é uma promessa de conformidade LGPD automática. O operador deve definir prazos, encarregado/canal, base legal e revisar os textos em termos/privacidade, que estão identificados como documentos iniciais.

## Testes

```bash
make test
make check
.venv/bin/python manage.py makemigrations --check --dry-run
```

Testes usam SQLite em memória e dados/imagens sintéticos. Execução usa PostgreSQL. Para produção, mantenha DEBUG=0, HTTPS, cookies seguros, backups criptografados, controle de acesso, limites no proxy e revisão de segurança/privacidade.

```bash
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

Não há Celery/Redis nem capturador neste novo portal. As antigas tabelas de clonagem não são apagadas pela migração e não são usadas pelo portal.
