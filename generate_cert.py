# D:\python\video\generate_cert.py
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime
import os

def generate_self_signed_cert():
    # 1. 确保 ssl 文件夹存在
    # 如果目录不存在则创建，避免路径报错
    ssl_dir = "ssl"
    if not os.path.exists(ssl_dir):
        os.makedirs(ssl_dir)
        print(f"已创建目录: {ssl_dir}")

    # 2. 生成私钥 (Private Key)
    # 使用 RSA 算法，密钥长度 4096 位
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )

    # 3. 生成自签名证书 (Certificate)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Zhejiang"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Ningbo"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"MyDevProject"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        # 有效期 365 天
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    ).sign(key, hashes.SHA256())

    # 4. 将私钥写入文件
    key_path = os.path.join(ssl_dir, "server.key")
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"私钥已生成: {key_path}")

    # 5. 将证书写入文件
    cert_path = os.path.join(ssl_dir, "server.crt")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"证书已生成: {cert_path}")

if __name__ == "__main__":
    generate_self_signed_cert()