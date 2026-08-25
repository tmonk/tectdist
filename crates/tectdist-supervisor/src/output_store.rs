//! Content-addressed store for output objects (plan workstream X5).
//!
//! Stores serialized page/resource objects keyed by their logical identity
//! and content digest. Supports the assembly planner by providing
//! lookup-by-digest for reuse decisions and atomic publication of results.
//!
//! Storage layout:
//!   <root>/<kind>/<digest-prefix-2>/<digest>
//!
//! Every object is verified on read (digest check) to prevent cache
//! poisoning (plan §17.2).

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use super::output_graph::{LogicalId, ObjectKind, StoredObject};
use super::output_graph::Digest;

/// Content-addressed store for output objects.
pub struct OutputStore {
    root: PathBuf,
}

impl OutputStore {
    pub fn open(root: impl Into<PathBuf>) -> Self {
        Self { root: PathBuf::from(Into::<PathBuf>::into(root)) }
    }

    fn kind_dir(&self, kind: ObjectKind) -> PathBuf {
        self.root.join(kind.as_str())
    }

    /// Store object bytes; returns the digest.
    pub fn put(&self, id: &LogicalId, bytes: &[u8]) -> Result<Digest, String> {
        let digest = sha256_hex(bytes);
        let dir = self.kind_dir(id.kind).join(&digest[..2]);
        fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let path = dir.join(&digest);
        // Atomic write: temp + rename.
        let tmp = path.with_extension("tmp");
        fs::write(&tmp, bytes).map_err(|e| e.to_string())?;
        fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
        Ok(digest)
    }

    /// Look up object bytes by digest; verifies integrity on read.
    pub fn get(&self, kind: ObjectKind, digest: &str) -> Result<Option<Vec<u8>>, String> {
        if digest.len() < 2 {
            return Ok(None);
        }
        let path = self.kind_dir(kind).join(&digest[..2]).join(digest);
        if !path.is_file() {
            return Ok(None);
        }
        let bytes = fs::read(&path).map_err(|e| e.to_string())?;
        let actual = sha256_hex(&bytes);
        if actual != digest {
            return Err(format!(
                "cache poisoning detected: expected digest {digest}, got {actual}"
            ));
        }
        Ok(Some(bytes))
    }

    /// Check whether an object exists without reading it.
    pub fn exists(&self, kind: ObjectKind, digest: &str) -> bool {
        if digest.len() < 2 {
            return false;
        }
        self.kind_dir(kind).join(&digest[..2]).join(digest).is_file()
    }

    /// Remove a specific object.
    pub fn remove(&self, kind: ObjectKind, digest: &str) -> Result<bool, String> {
        if digest.len() < 2 {
            return Ok(false);
        }
        let path = self.kind_dir(kind).join(&digest[..2]).join(digest);
        if path.is_file() {
            fs::remove_file(&path).map_err(|e| e.to_string())?;
            return Ok(true);
        }
        Ok(false)
    }

    /// Total number of objects across all kinds (approximate).
    pub fn count(&self) -> Result<usize, String> {
        let mut count = 0;
        for kind_dir_name in ["page", "font", "image", "annot", "resdict"] {
            let dir = self.root.join(kind_dir_name);
            if !dir.is_dir() {
                continue;
            }
            for subdir in fs::read_dir(&dir).map_err(|e| e.to_string())?.flatten() {
                if subdir.path().is_dir() {
                    count += fs::read_dir(subdir.path())
                        .map_err(|e| e.to_string())?
                        .count();
                }
            }
        }
        Ok(count)
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TempDir(PathBuf);

    impl TempDir {
        fn new() -> std::io::Result<Self> {
            let dir = std::env::temp_dir().join(
                format!("bt100-store-{}", std::process::id()));
            fs::create_dir_all(&dir)?;
            Ok(Self(dir))
        }
        fn path(&self) -> &Path { &self.0 }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn put_get_roundtrip_preserves_content() {
        let dir = TempDir::new().unwrap();
        let store = OutputStore::open(dir.path());
        let id = LogicalId::new(ObjectKind::Page, "test-page");
        let data = b"page content bytes";
        let digest = store.put(&id, data).unwrap();
        assert_eq!(digest.len(), 64);
        let loaded = store.get(ObjectKind::Page, &digest).unwrap();
        assert_eq!(loaded.as_deref(), Some(data.as_slice()));
    }

    #[test]
    fn get_missing_returns_none() {
        let dir = TempDir::new().unwrap();
        let store = OutputStore::open(dir.path());
        let result = store.get(ObjectKind::Page, "nonexistent").unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn detects_cache_poisoning_on_read() {
        let dir = TempDir::new().unwrap();
        let store = OutputStore::open(dir.path());
        let id = LogicalId::new(ObjectKind::Image, "img");
        let digest = store.put(&id, b"original").unwrap();

        // Tamper with the stored file.
        let path = dir.path()
            .join("image")
            .join(&digest[..2])
            .join(&digest);
        fs::write(&path, b"tampered").unwrap();

        let result = store.get(ObjectKind::Image, &digest);
        assert!(result.is_err(), "poisoned entry must be rejected");
    }

    #[test]
    fn remove_deletes_entry() {
        let dir = TempDir::new().unwrap();
        let store = OutputStore::open(dir.path());
        let id = LogicalId::new(ObjectKind::FontProgram, "cmr10");
        let digest = store.put(&id, b"font-data").unwrap();
        assert!(store.exists(ObjectKind::FontProgram, &digest));
        store.remove(ObjectKind::FontProgram, &digest).unwrap();
        assert!(!store.exists(ObjectKind::FontProgram, &digest));
    }

    #[test]
    fn counts_objects_across_kinds() {
        let dir = TempDir::new().unwrap();
        let store = OutputStore::open(dir.path());
        store.put(&LogicalId::new(ObjectKind::Page, "p"), b"a").unwrap();
        store.put(&LogicalId::new(ObjectKind::FontProgram, "f"), b"b").unwrap();
        assert_eq!(store.count().unwrap(), 2);
    }
}
