#!/bin/bash

set -x

# Source the .env file
if [ -f .env.nginx ]; then
  export $(grep -v '^#' .env.nginx | xargs)
fi

is_debug=$1

domains=(${APP_DOMAIN})
rsa_key_size=4096
data_path="./nginx/certbot"
email="${SSL_EMAIL}"

if [ -d "$data_path" ]; then
    read -p "Existing data found for $domains. Continue and replace existing certificate? (y/N) " decision
    if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
        exit
    fi
fi

if [ ! -e "$data_path/conf/options-ssl-nginx.conf" ] || [ ! -e "$data_path/conf/ssl-dhparams.pem" ]; then
    echo "### Downloading recommended TLS parameters ..."
    mkdir -p "$data_path/conf"
    ret=$(curl -s -w "%{http_code}" -o "$data_path/conf/options-ssl-nginx.conf" "https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf")
    if [ "$ret" -ne 200 ]; then
      exit 1;
    fi
    ret=$(curl -s -w "%{http_code}" -o "$data_path/conf/ssl-dhparams.pem" "https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem")
    if [ "$ret" -ne 200 ]; then
      exit 1;
    fi
    echo
fi

echo "### Creating dummy certificate for $domains ..."
path="/etc/letsencrypt/live/$domains"
mkdir -p "$data_path/conf/live/$domains"
docker compose -f "docker-compose.yaml" run --rm --entrypoint "openssl req -x509 -nodes -newkey rsa:4096 -days 1 -keyout '/etc/letsencrypt/live/share.alchemono.org/privkey.pem' -out '/etc/letsencrypt/live/share.alchemono.org/fullchain.pem' -subj '/CN=localhost'" certbot
echo

if [ "$is_debug" == "--debug" ]; then
  echo "### Debug mode: Skipping nginx start and certificate issuance."
  exit 0
fi

echo "### Starting nginx ..."
docker compose  -f "docker-compose.yaml" up --force-recreate nginx
echo

echo "### Deleting dummy certificate for $domains ..."
docker compose  -f "docker-compose.yaml" run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domains && \
  rm -Rf /etc/letsencrypt/archive/$domains && \
  rm -Rf /etc/letsencrypt/renewal/$domains.conf" certbot
echo

echo "### Requesting Let's Encrypt certificate for $domains ..."
#Join $domains to -d args
domain_args=""
for domain in "${domains[@]}"; do
    domain_args="$domain_args -d $domain"
done

docker compose -f "docker-compose.yaml" run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $email \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot
echo

