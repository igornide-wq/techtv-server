# TechTV Server — App Mobile Web

## Como hospedar GRATUITAMENTE no Railway

1. Crie uma conta em **railway.app**
2. Clique em "New Project" → "Deploy from GitHub"
3. Faça upload desta pasta ou conecte ao GitHub
4. Configure as variáveis de ambiente:
   - `API_SECRET` = uma senha secreta (ex: MinhaChave2025!)
   - `DATA_FILE`  = dados_server.json
5. O Railway vai gerar uma URL tipo: `https://techtv-server.up.railway.app`

## Como hospedar no Render (alternativa gratuita)

1. Crie conta em **render.com**
2. New → Web Service → conecte o repositório
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
5. Adicione as variáveis de ambiente acima

## Configurar no TechTV Desktop

Após hospedar, abra o TechTV → Arquivo → Configurações → aba Servidor:
- URL do servidor: `https://sua-url.railway.app`
- Chave de sincronização: (a mesma que você colocou em API_SECRET)

## Como o cliente consulta a OS

O cliente acessa pelo celular:
`https://sua-url.railway.app`

Clica em "Consultar aqui" → digita o número da OS → vê o status em tempo real.

## Como você acessa como admin

Mesma URL → faz login com:
- E-mail: admin@techtv.com
- Senha: admin123

⚠️ **Troque a senha após o primeiro acesso!**

## Sincronização

No TechTV Desktop, após configurar o servidor:
- **Arquivo → Sincronizar com servidor** = envia todas as OS para a nuvem
- A sincronização também ocorre automaticamente ao salvar uma OS

## Segurança

- Troque o `API_SECRET` para algo único e seguro
- Troque a senha do admin após o primeiro login
- A consulta pública só mostra status — sem dados financeiros
