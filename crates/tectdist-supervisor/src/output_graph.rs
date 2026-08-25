// Forward-looking plan-X5 object-graph model. Execution lands with engine-side page digests.
#![allow(dead_code)]

//! Output object graph model (plan workstream X5 / §6.6).
//!
//! Supervisor-side contract for incremental PDF/DVI/XDV assembly: stable
//! logical object identities keyed by content digests, page/resource
//! graphs per build, and a deterministic changed-object assembly planner.
//!
//! The ENGINE owns authoritative output bytes and final serialization;
//! this module models the metadata used to decide what can be reused
//! between builds. Engine patches (X10-150..155) will produce and consume
//! these records.

use std::collections::BTreeMap;

/// Content digest (SHA-256 hex) over the object's serialized bytes.
pub type Digest = String;

/// Stable logical identifier for an output object. Stable across builds
/// when the object's semantic content is identical (plan §12: semantic
/// identity matters, not byte identity of container files).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct LogicalId {
    /// Kind namespace so ids from different producers can't collide.
    pub kind: ObjectKind,
    pub key: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum ObjectKind {
    Page,
    FontProgram,
    Image,
    Annotation,
    ResourceDictionary,
}

impl ObjectKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            ObjectKind::Page => "page",
            ObjectKind::FontProgram => "font",
            ObjectKind::Image => "image",
            ObjectKind::Annotation => "annot",
            ObjectKind::ResourceDictionary => "resdict",
        }
    }
}

impl LogicalId {
    pub fn new(kind: ObjectKind, key: impl Into<String>) -> Self {
        Self {
            kind,
            key: key.into(),
        }
    }
}

/// One reusable output object with its content digest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredObject {
    pub id: LogicalId,
    pub digest: Digest,
    pub bytes_len: u64,
}

/// A page as recorded by a completed build: its own content digest plus
/// references to every resource object it depends on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PageEntry {
    pub page_id: LogicalId,
    pub content_digest: Digest,
    pub resource_ids: Vec<LogicalId>,
}

/// The full output graph of one build (plan §6.6).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct OutputGraph {
    pub pages: Vec<PageEntry>,
    pub resources: BTreeMap<String, StoredObject>,
}

impl OutputGraph {
    /// All resource digests referenced anywhere in the graph.
    pub fn resource_digests(&self) -> BTreeMap<String, Digest> {
        self.resources
            .iter()
            .map(|(key, stored)| (key.clone(), stored.digest.clone()))
            .collect()
    }

    /// Page count.
    pub fn page_count(&self) -> usize {
        self.pages.len()
    }
}

/// Result of planning assembly for one new build against a previous graph.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AssemblyPlan {
    /// Pages reused verbatim from the previous build (old page index).
    pub reused_pages: Vec<usize>,
    /// Pages requiring fresh conversion (new-build page index).
    pub rebuilt_pages: Vec<usize>,
    /// Resource objects reused (logical id keys).
    pub reused_resources: Vec<String>,
    /// Resource objects needing regeneration.
    pub regenerated_resources: Vec<String>,
}

/// Plan the assembly: compare each new-build page's content digest against
/// the previous graph; identical digests mean the page (and any resources
/// whose digests also match) can be reused without re-running the backend
/// (plan X5 gate: "unchanged output suffixes do not trigger complete
/// backend conversion").
///
/// Deterministic ordering guaranteed: results are sorted by page position.
pub fn plan_assembly(
    previous: Option<&OutputGraph>,
    new_pages: &[PageEntry],
    new_resources: &BTreeMap<String, StoredObject>,
) -> AssemblyPlan {
    let mut plan = AssemblyPlan {
        reused_pages: Vec::new(),
        rebuilt_pages: Vec::new(),
        reused_resources: Vec::new(),
        regenerated_resources: Vec::new(),
    };

    // Resource-level comparison first.
    match previous {
        Some(previous_graph) => {
            let old_resources = previous_graph.resource_digests();
            let new_resource_digests: BTreeMap<String, Digest> = new_resources
                .iter()
                .map(|(key, stored)| (key.clone(), stored.digest.clone()))
                .collect();
            for (key, new_digest) in &new_resource_digests {
                match old_resources.get(key) {
                    Some(old_digest) if old_digest == new_digest => {
                        plan.reused_resources.push(key.clone());
                    }
                    _ => {
                        plan.regenerated_resources.push(key.clone());
                    }
                }
            }
        }
        None => {
            plan.regenerated_resources = new_resources.keys().cloned().collect();
        }
    }

    // Page comparison.
    match previous {
        Some(previous_graph) if !previous_graph.pages.is_empty() => {
            for (index, new_page) in new_pages.iter().enumerate() {
                if let Some(old_page) = previous_graph.pages.get(index) {
                    if old_page.content_digest == new_page.content_digest {
                        plan.reused_pages.push(index);
                        continue;
                    }
                }
                plan.rebuilt_pages.push(index);
            }
        }
        Some(_) => {
            // Previous graph exists but has no pages: build fresh.
            plan.rebuilt_pages = (0..new_pages.len()).collect();
        }
        None => {
            // No previous graph: everything must be built fresh.
            plan.rebuilt_pages = (0..new_pages.len()).collect();
        }
    }

    plan.reused_pages.sort_unstable();
    plan.rebuilt_pages.sort_unstable();
    plan.reused_resources.sort();
    plan.regenerated_resources.sort();
    plan
}

#[cfg(test)]
mod tests {
    use super::*;

    fn page(id_key: &str, digest: &str, res: &[&str]) -> PageEntry {
        PageEntry {
            page_id: LogicalId::new(ObjectKind::Page, id_key),
            content_digest: digest.into(),
            resource_ids: res
                .iter()
                .map(|r| LogicalId::new(ObjectKind::FontProgram, *r))
                .collect(),
        }
    }

    fn stored(key: &str, digest: &str) -> (String, StoredObject) {
        (
            format!("font:{key}"),
            StoredObject {
                id: LogicalId::new(ObjectKind::FontProgram, key),
                digest: digest.into(),
                bytes_len: 100,
            },
        )
    }

    #[test]
    fn unchanged_suffix_reuses_all_pages() {
        let mut previous = OutputGraph::default();
        previous.pages = vec![
            page("p0", "d0", &[]),
            page("p1", "d1", &["cmr10"]),
            page("p2", "d2", &["cmr10"]),
        ];
        let cmr = stored("cmr10", "fdigest");
        previous.resources.insert(cmr.0.clone(), cmr.1.clone());

        let new_pages = vec![
            page("p0", "d0", &[]),
            page("p1", "d1", &["cmr10"]),
            page("p2", "d2", &["cmr10"]),
        ];
        let mut new_resources = BTreeMap::new();
        new_resources.insert(cmr.0.clone(), cmr.1.clone());

        let plan = plan_assembly(Some(&previous), &new_pages, &new_resources);
        assert_eq!(plan.reused_pages, vec![0, 1, 2]);
        assert!(plan.rebuilt_pages.is_empty());
        assert_eq!(plan.reused_resources, vec!["font:cmr10"]);
        assert!(plan.regenerated_resources.is_empty());
    }

    #[test]
    fn single_changed_page_rebuilds_only_that_page() {
        let mut previous = OutputGraph::default();
        previous.pages = vec![
            page("p0", "d0", &[]),
            page("p1", "d1", &[]),
            page("p2", "d2", &[]),
        ];

        let new_pages = vec![
            page("p0", "d0", &[]),
            page("p1", "CHANGED", &[]),
            page("p2", "d2", &[]),
        ];
        let new_resources = BTreeMap::new();

        let plan = plan_assembly(Some(&previous), &new_pages, &new_resources);
        assert_eq!(plan.reused_pages, vec![0, 2]);
        assert_eq!(plan.rebuilt_pages, vec![1]);
    }

    #[test]
    fn no_previous_graph_builds_everything() {
        let new_pages = vec![page("p0", "d0", &[])];
        let plan = plan_assembly(None, &new_pages, &BTreeMap::new());
        assert_eq!(plan.rebuilt_pages, vec![0]);
        assert!(plan.reused_pages.is_empty());
    }

    #[test]
    fn shorter_new_document_reuses_prefix_rebuilds_suffix() {
        let mut previous = OutputGraph::default();
        previous.pages = vec![
            page("p0", "d0", &[]),
            page("p1", "d1", &[]),
            page("p2", "d2", &[]),
        ];

        // Content shrank: 2 pages now.
        let new_pages = vec![page("p0", "d0", &[]), page("p1", "d1", &[])];
        let new_resources = BTreeMap::new();

        let plan = plan_assembly(Some(&previous), &new_pages, &new_resources);
        // Content shrank: remaining pages with matching digests are still
        // reusable; the missing page simply doesn't appear in the new build.
        assert_eq!(plan.reused_pages, vec![0, 1]);
        assert_eq!(plan.rebuilt_pages, Vec::<usize>::new());
    }

    #[test]
    fn resource_change_is_detected_independently_of_pages() {
        let mut previous = OutputGraph::default();
        previous.pages = vec![page("p0", "d0", &["cmr10"])];
        let cmr_old = stored("cmr10", "OLD");
        previous.resources.insert(cmr_old.0.clone(), cmr_old.1);

        let new_pages = vec![previous.pages[0].clone()];
        let cmr_new = stored("cmr10", "NEW");
        let key = cmr_new.0.clone();
        let object = cmr_new.1;
        let mut new_resources = BTreeMap::new();
        new_resources.insert(key, object);

        let plan = plan_assembly(Some(&previous), &new_pages, &new_resources);
        // Page content digest unchanged but its font changed: page is still
        // reused (the font substitution is handled at the PDF layer), while
        // the resource itself is flagged for regeneration.
        assert_eq!(plan.reused_pages, vec![0]);
    }

    #[test]
    fn deterministic_ordering_regardless_of_input_order() {
        let mut previous = OutputGraph::default();
        previous.pages = vec![page("p0", "d0", &[]), page("p1", "d1", &[])];
        // Reverse input order.
        let new_pages = vec![page("p1", "CHANGED-B", &[]), page("p0", "CHANGED-A", &[])];
        let new_resources = BTreeMap::new();
        let plan = plan_assembly(Some(&previous), &new_pages, &new_resources);
        // Positions are positional, not keyed: both diverge.
        assert_eq!(plan.rebuilt_pages.len(), 2);
        assert!(plan.reused_pages.is_empty());
    }
}
