use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use anyhow::{anyhow, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use rand::RngCore;

#[derive(Clone)]
pub struct Crypto {
    cipher: Aes256Gcm,
}

impl Crypto {
    pub fn new(key_b64: &str) -> Result<Self> {
        let key = STANDARD
            .decode(key_b64.trim())
            .map_err(|_| anyhow!("ENCRYPTION_KEY must be valid base64"))?;
        if key.len() != 32 {
            return Err(anyhow!("ENCRYPTION_KEY decoded length must be exactly 32 bytes"));
        }
        let cipher = Aes256Gcm::new_from_slice(&key).map_err(|_| anyhow!("invalid encryption key"))?;
        Ok(Self { cipher })
    }

    pub fn encrypt(&self, plaintext: &str) -> Result<String> {
        let mut nonce_bytes = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);
        let ciphertext = self
            .cipher
            .encrypt(nonce, plaintext.as_bytes())
            .map_err(|_| anyhow!("encryption failed"))?;

        let mut packed = Vec::with_capacity(12 + ciphertext.len());
        packed.extend_from_slice(&nonce_bytes);
        packed.extend_from_slice(&ciphertext);
        Ok(STANDARD.encode(packed))
    }

    pub fn decrypt(&self, encrypted_b64: &str) -> Result<String> {
        let raw = STANDARD
            .decode(encrypted_b64.trim())
            .map_err(|_| anyhow!("ciphertext is not valid base64"))?;
        if raw.len() < 13 {
            return Err(anyhow!("ciphertext is too short"));
        }
        let (nonce_part, ciphertext_part) = raw.split_at(12);
        let nonce = Nonce::from_slice(nonce_part);
        let plaintext = self
            .cipher
            .decrypt(nonce, ciphertext_part)
            .map_err(|_| anyhow!("decryption failed"))?;
        Ok(String::from_utf8(plaintext).map_err(|_| anyhow!("decrypted data is not utf-8"))?)
    }
}
