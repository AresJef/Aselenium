# Public, test-only loopback TLS identity

The certificate and private key in this directory are intentionally public test
fixtures. They identify only `127.0.0.1` and `localhost`, with validity from
2020-01-01 through 2100-01-01. They must never secure a real service or be added to
the operating system's trusted certificate store.

Tests load the certificate into their own explicitly constructed client SSL
context and bind their TLS listener only to an ephemeral loopback port. Default
TLS contexts must reject this self-signed identity. Fixture generation used
OpenSSL once; running the tests requires only Python's standard `ssl` module.
