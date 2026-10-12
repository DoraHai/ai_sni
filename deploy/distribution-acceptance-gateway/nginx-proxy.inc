# One fixed, strictly authenticated SEO acceptance upstream, no redirects/cookie reuse.
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $http_host;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header Authorization $http_authorization;
proxy_set_header Cookie "";
proxy_hide_header Set-Cookie;
proxy_redirect off;
proxy_buffering off;
proxy_connect_timeout 3s;
proxy_read_timeout 35s;
proxy_send_timeout 35s;
# Installed nginx uses X509_check_host. SAN DNS:localhost is valid; IP hostname verification is not.
proxy_ssl_server_name on;
proxy_ssl_name localhost;
proxy_ssl_verify on;
proxy_ssl_verify_depth 2;
proxy_ssl_trusted_certificate /opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012/loopback.pem;
