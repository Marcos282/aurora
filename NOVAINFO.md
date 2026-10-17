# Nova Info no ambiente Aurora

O ambiente Python, o PostgreSQL configurado, a autenticação Django e o Bootstrap local foram reaproveitados. A interface do estabelecimento passa a ser o Nova Info. O código e as migrações antigas continuam disponíveis; `/admin/` e `/gestao/` foram preservados. Nenhum arquivo `.env`, configuração de produção, registro do banco atual ou roteador foi alterado nesta implementação. Não houve deploy ou envio ao GitHub.

## Arquitetura adotada

Não havia tenant, WireGuard ou integração MikroTik no código recebido. Por isso, a integração foi implementada em um único aplicativo `hotspot`, sem afirmar que já existia infraestrutura operacional.

- Estabelecimento (`Tenant`), vínculo por conta (`Membership`) e permissões de responsável, atendente e consulta.
- Cada conta pertence a um estabelecimento. A conta autenticada determina o tenant; parâmetros `tenant_id` do navegador não são utilizados.
- Se configurado, o subdomínio deve corresponder ao estabelecimento da conta. Subdomínios desconhecidos são recusados. Login entre estabelecimentos também é recusado.
- Um roteador exclusivo por estabelecimento, com IP privado único no WireGuard. O backend verifica tanto a rota quanto o tipo da interface WireGuard antes de **cada** chamada.
- RouterOS 7 com REST API HTTPS, CA confiável e certificado válido para o IP do túnel. Sem HTTP, redirecionamentos ou proxies herdados do ambiente.
- Página de conexão hospedada no Django. A imagem e a mensagem mudam imediatamente, sem sincronizar arquivos de imagem para o MikroTik. O roteador precisa apenas de um `login.html` de redirecionamento inicial.
- Os uploads são validados pelo conteúdo e tamanho, limitados a 5 MB e 16 megapixels, convertidos para WebP e têm os metadados removidos.
- A URL pública da imagem expõe somente a imagem daquele estabelecimento, sem credenciais ou informações de sessões. O UUID da URL é um identificador público, não uma credencial.
- As sessões online são consultadas diretamente no Hotspot configurado. Não existe fallback para sessões em cache. O horário de consulta é exibido; atualizar dispara nova consulta.

Referências da implementação: [REST API do RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API), [HotSpot](https://help.mikrotik.com/docs/spaces/ROS/pages/56459266/HotSpot+-+Captive+portal) e [limites de usuário](https://wiki.mikrotik.com/index.php?title=Manual:IP/Hotspot/User).

## Tempo e dispositivos

Conforme confirmado, a credencial permite **1 a 6 dispositivos simultâneos**. O perfil utiliza `shared-users` com esse limite. O atendente escolhe um plano de **1, 3 ou 6 horas**. A credencial recebe `limit-uptime=1h`, `3h` ou `6h`; o perfil limita cada sessão ao mesmo tempo. Os perfis são separados por estabelecimento, quantidade de dispositivos e duração.

A duração escolhida representa **uso acumulado da credencial**, conforme a contagem do MikroTik. Não representa expiração após a emissão nem uma cota individual para cada dispositivo. Desconectar não renova a cota. A contagem com vários dispositivos precisa ser homologada no RouterOS utilizado antes de operação real.

O atendente escolhe o usuário e a senha no formulário Criar Acesso. O nome aceita de 3 a 40 caracteres (letras, números, ponto, hífen ou sublinhado) e a senha, de 8 a 64 caracteres. Nomes não podem se repetir no mesmo estabelecimento; estabelecimentos distintos podem usar o mesmo nome em seus roteadores exclusivos. As senhas são criptografadas e mostradas apenas na confirmação da criação ao atendente que a solicitou. O histórico não revela senhas. O link do WhatsApp somente abre uma mensagem para o atendente escolher o destinatário e confirmar o envio.

A criação faz uma consulta de disponibilidade antes de alterar o roteador. Uma mesma solicitação não cria novas credenciais ao ser reenviada. Um timeout durante uma alteração deixa a solicitação em **Requer conferência**: pode ter ocorrido criação no MikroTik, então não há repetição automática. O suporte deve conferir o usuário e o comentário de UUID no roteador antes de outra tentativa. Nenhum tratamento de timeout consegue oferecer atomicidade entre PostgreSQL e RouterOS; o nome escolhido é enviado sem alteração ao roteador; uma tentativa de recriar um nome existente não altera a conta que já está no MikroTik.

Acessos antigos de 2 horas são preservados no histórico e na migração; o formulário e o serviço de criação aceitam somente 1, 3 ou 6 horas. A restrição SQL mantém 7200 segundos apenas por compatibilidade com esses registros antigos.

## Preparação local para revisão

Na pasta do projeto, usando o ambiente existente:

```bash
cd /home/marcos/Documents/projetos/aurora/aurora
source myenv/bin/activate
python manage.py check
python manage.py migrate --plan
```

As migrações foram geradas, mas **não foram aplicadas ao banco existente**. Após revisar o plano e confirmar o banco configurado, aplique-as:

```bash
python manage.py migrate
python manage.py provision_tenant pousada-azul "Pousada Azul" recepcao
python manage.py runserver 8002
```

O comando solicita a senha sem exibir caracteres se a conta for nova. Se a conta já existe, a senha é preservada. Contas vinculadas a outro tenant não são transferidas. Um usuário sem vínculo recebe uma tela explicando que precisa ser associado a um estabelecimento; ser superusuário não libera acesso aos dados de todos os estabelecimentos no painel.

Acesse `http://localhost:8002/`. Não é necessário configurar o roteador para revisar as telas: a consulta online mostrará indisponibilidade e a criação não será confirmada sem conexão real.

## Configuração operacional, sem alterar o `.env` automaticamente

Forneça estas variáveis pelo gerenciador de segredos ou pelo ambiente da aplicação:

| Variável | Uso |
| --- | --- |
| `NOVAINFO_CREDENTIAL_KEY` | Chave Fernet exclusiva e estável para as senhas do roteador e dos acessos. |
| `NOVAINFO_WIREGUARD_INTERFACE` | Nome da interface real no servidor; padrão `wg0`. |
| `NOVAINFO_WIREGUARD_NETWORKS` | Redes permitidas do túnel, separadas por vírgulas, por exemplo `10.66.0.0/24`. Sem configuração, toda conexão é bloqueada. |
| `NOVAINFO_ROUTER_CA` | Caminho do arquivo PEM da CA do roteador, se não for uma CA já confiável no sistema. A verificação TLS permanece ativa. |
| `NOVAINFO_BASE_DOMAIN` | Opcional, domínio base para resolver `pousada-azul.seudominio.com.br`. |
| `DJANGO_ALLOWED_HOSTS` | Hosts reais do painel; inclua `.seudominio.com.br` apenas quando configurar os subdomínios. Use vírgulas como separador. |

Para gerar uma chave localmente: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Guarde-a no gerenciador de segredos e mantenha backup. Não troque a chave sem migrar os dados criptografados. Não use as chaves dos módulos de testes.

A interface WireGuard, seus peers, as rotas e as regras de firewall devem ser provisionados pelo operador no servidor. Este código não cria túneis, não instala serviços e não modifica roteadores automaticamente. O banco em execução deve usar uma conta **NOSUPERUSER NOBYPASSRLS** para que o PostgreSQL aplique RLS.

Configure uma conta RouterOS dedicada, com o menor conjunto de permissões necessário à leitura de sessões e criação de usuários/perfis, e restrinja `www-ssl` ao IP do servidor no túnel. A API requer RouterOS 7. O nome do servidor Hotspot precisa ser informado explicitamente e deve ser diferente do valor especial `all`.

```bash
python manage.py configure_router pousada-azul \
  --ip 10.66.0.2 \
  --api-user novainfo-api \
  --hotspot-server hotspot1 \
  --login-url https://wifi.pousada.example/login
```

O comando solicita a senha da API sem eco e a armazena criptografada. A URL `--login-url` é o endpoint HTTPS **do Hotspot acessível ao hóspede**, com certificado válido; não é a URL da REST API nem deve conter senha ou parâmetros. O formulário de hóspedes envia somente a credencial Wi-Fi para esse endpoint; credenciais administrativas continuam exclusivamente no backend.

## Página externa do Hotspot

Publique a aplicação em HTTPS antes da integração real. Gere o arquivo inicial para o roteador, sem tocar no equipamento:

```bash
python manage.py export_hotspot_login pousada-azul \
  --origin https://painel.seudominio.com.br > /tmp/novainfo-login.html
```

O operador deve revisar e instalar esse arquivo como `login.html` na pasta do Hotspot correspondente. O arquivo apenas redireciona para `/hotspot/UUID/` no Django. Não contém segredos.

No MikroTik, libere no walled garden o domínio HTTPS da página externa e seus arquivos estáticos e imagens. O login do Hotspot deve aceitar autenticação por HTTPS/PAP com certificado válido; a implementação não oferece CHAP nem transporte HTTP de senha. Mantenha o domínio público do portal diferente do domínio de login do roteador e garanta a resolução DNS na rede dos hóspedes. Não há alteração automática de walled garden, autenticação, certificados ou arquivos do roteador.

Somente as imagens e os campos públicos de apresentação são expostos nas rotas `/hotspot/UUID/`. O painel usa login, CSRF, verificação de vínculo e permissões; a resposta com credenciais tem `Cache-Control: no-store` e política de referrer que impede envio do endereço de origem ao WhatsApp.

## Isolamento PostgreSQL

A migração `hotspot.0002_tenant_rls` adiciona `ENABLE/FORCE ROW LEVEL SECURITY` exclusivamente às tabelas novas de roteador, personalização, acessos e auditoria. As políticas antigas não são removidas nem modificadas.

As consultas autenticadas executam dentro de transação com `SET LOCAL novainfo.tenant_id`. O contexto é restaurado em chamadas aninhadas e não persiste em conexões reutilizadas. Sem contexto, as tabelas protegidas não retornam registros. A consulta pública de imagem define somente o contexto do UUID solicitado e entrega exclusivamente a imagem. O diretório de tenants e os vínculos são consultados para resolver a identidade; o usuário do navegador não escolhe vínculos.

As contas de administração do PostgreSQL com SUPERUSER ou BYPASSRLS ignoram RLS por definição. Não use essas contas na aplicação. Os filtros explícitos por tenant continuam presentes mesmo com RLS. As migrações e a provisão de tenants são ações do operador, fora das páginas dos estabelecimentos.

## Validação

```bash
python manage.py test hotspot --settings=config.novainfo_test_settings
python manage.py test core --settings=config.test_settings
python manage.py makemigrations --check --dry-run --settings=config.novainfo_test_settings
python manage.py check
```

A suíte cobre isolamento por conta/subdomínio, permissões, CSRF, criação e reenvio, limites de 1 a 6, timeout, indisponibilidade, upload, troca de wallpaper, criptografia, rota/interface WireGuard, TLS, alterações de senha e preservação das telas administrativas. Chamadas ao RouterOS são simuladas nos testes; isso não comprova conectividade real.

O teste RLS é executado separadamente em um cluster PostgreSQL descartável, sem usar o banco existente, com o módulo `config.novainfo_postgres_test_settings`. Esse módulo só aponta para o socket de teste `/tmp/novainfo-pg-socket`, porta 55439. O cluster de teste deve possuir o superusuário de teste `novainfo_test_admin` e o papel `novainfo_rls_test NOSUPERUSER NOBYPASSRLS`; não use esse módulo em produção.

Antes de uso comercial, ainda é necessário validar com o equipamento real: túnel, certificado, permissões da API, login do hóspede, expiração por tempo, simultaneidade, walled garden e mudança de imagem. Nenhum resultado de teste com mocks é apresentado como homologação do roteador.
