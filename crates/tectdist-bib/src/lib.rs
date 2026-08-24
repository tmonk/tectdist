//! tectdist-bib: groundwork for a native bibliography fast path (plan X6).
//!
//! Scope of this crate today:
//! - a robust `.bib` database parser (balanced braces, string concatenation,
//!   `@string`/`@comment`/`@preamble`, month macros),
//! - an entry model with name parsing (`First von Last`) and label fields,
//! - numeric (plain-style) sorting and `.bbl` emission for the bounded
//!   common subset,
//! - a capability model that classifies requests as supported or fallback.
//!
//! The driver-level integration is deliberately NOT wired yet: Biber runs
//! inside Tectonic's processing session (`external_tool_pass`), so replacing
//! it requires the same upstreamable stage-interception patches as plan
//! items X5.1/X10-045. Until that lands, every request falls back to
//! external Biber and this crate's emitter is exercised only through its own
//! differential tests.

pub mod bib;
pub mod bbl;

/// Classification of one bibliography request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Capability {
    /// Numeric-label style over the supported entry/field subset; the native
    /// emitter may serve this once driver integration exists.
    Supported,
    /// Anything outside the subset (sourcemaps, custom data models, remote
    /// data sources, name/label schemes beyond numeric): external Biber must
    /// handle the whole request. No partial mixing, per plan X6.2.
    Fallback(&'static str),
}

#[cfg(test)]
mod tests {
    use crate::bib::parse;
    use crate::bbl::{capability, emit_bbl, parse_name};

    const CORPUS_BIB: &str = r#"
@article{knuth84,
  author  = {Donald E. Knuth},
  title   = {The {TeX}book},
  journal = {Computing Systems},
  year    = {1984},
  volume  = {1}
}
@book{lamport86,
  author    = {Leslie Lamport},
  title     = {LaTeX: A Document Preparation System},
  publisher = {Addison-Wesley},
  year      = {1986}
}
@misc{misc99,
  title = {Miscellaneous Entry},
  year  = {1999}
}
"#;

    #[test]
    fn parses_entries_strings_and_months() {
        let database = parse(CORPUS_BIB).unwrap();
        assert_eq!(database.entries.len(), 3);
        let knuth = &database.entries[0];
        assert_eq!(knuth.get("journal"), Some("Computing Systems"));
        assert_eq!(knuth.get("volume"), Some("1"));
    }

    #[test]
    fn handles_concatenation_and_string_macros() {
        let database = parse(
            "@string{conf = \"Conference\"}\n\
             @misc{x, booktitle = \"Proc. of \" # conf # \" 2020\"}\n",
        )
        .unwrap();
        let entry = &database.entries[0];
        assert_eq!(entry.get("booktitle"), Some("Proc. of Conference 2020"));
    }

    #[test]
    fn survives_comments_and_preambles() {
        let database = parse(
            "@comment{this is {nested} comment text}\n@preamble{\"x\"}\n\
             @article{a, title = {T}}\n",
        )
        .unwrap();
        assert_eq!(database.entries.len(), 1);
    }

    #[test]
    fn parses_von_and_comma_names() {
        assert_eq!(
            parse_name("Ludwig van Beethoven"),
            ("Beethoven".to_string(), "L".to_string())
        );
        assert_eq!(
            parse_name("van Beethoven, Ludwig"),
            ("Beethoven".to_string(), "L".to_string())
        );
        assert_eq!(parse_name("Knuth"), ("Knuth".to_string(), "".to_string()));
    }

    #[test]
    fn numeric_capability_gates_unknown_fields() {
        let database = parse(CORPUS_BIB).unwrap();
        assert_eq!(capability(&database, "plain"), crate::Capability::Supported);
        let exotic = parse("@article{a, orcid = {0000}}\n").unwrap();
        assert!(matches!(capability(&exotic, "plain"),
                         crate::Capability::Fallback(_)));
        assert!(matches!(capability(&database, "authoryear"),
                         crate::Capability::Fallback(_)));
    }

    #[test]
    fn emits_sorted_numeric_bbl() {
        let database = parse(CORPUS_BIB).unwrap();
        let cited = vec![
            "lamport86".to_string(),
            "knuth84".to_string(),
        ];
        let bbl = emit_bbl(&database, &cited);
        assert!(bbl.contains("\\begin{thebibliography}{}"));
        assert!(bbl.contains("\\bibitem{knuth84}"));
        assert!(bbl.contains("\\bibitem{lamport86}"));
        // Knuth (1984) sorts before Lamport (1986) by author label.
        assert!(bbl.find("knuth84").unwrap() < bbl.find("lamport86").unwrap());
        // Uncited entries are omitted.
        assert!(!bbl.contains("misc99"));
    }
}
