//! Numeric (plain-style) `.bbl` emission for the bounded subset, plus the
//! capability classifier and a name parser for sort labels.

use crate::bib::{Database, Entry};
use std::collections::BTreeMap;

/// Parse one BibTeX name into von-part detection for sort keys
/// (`First von Last` / `von Last, First`). Returns (last, first-initial).
pub fn parse_name(name: &str) -> (String, String) {
    let name = name.trim();
    if let Some((last_part, first_part)) = name.split_once(',') {
        let last = last_part.trim();
        // Drop a trailing von-part if present ("von Last").
        let last_words: Vec<&str> = last.split_whitespace().collect();
        let mut keep = Vec::new();
        for word in last_words.iter().rev() {
            let starts_lower = word.chars().next().map(|c| c.is_lowercase()).unwrap_or(false);
            if starts_lower {
                break;
            }
            keep.push(*word);
        }
        keep.reverse();
        let pure_last = keep.join(" ");
        let last = if pure_last.is_empty() { last } else { &pure_last };
        let initial = first_part
            .trim()
            .chars()
            .next()
            .map(String::from)
            .unwrap_or_default();
        return (debrace(last).to_string(), initial);
    }
    let words: Vec<&str> = name.split_whitespace().collect();
    if words.len() <= 1 {
        return (debrace(name).to_string(), String::new());
    }
    // Find the von section: lowercase words between first and last.
    let mut split = 0;
    for (index, word) in words.iter().enumerate() {
        let starts_lower =
            word.chars().next().map(|c| c.is_lowercase()).unwrap_or(false);
        if starts_lower && index > 0 && index < words.len() - 1 {
            split = index + 1;
        }
    }
    let last = words[split..].join(" ");
    let initial = words[0].chars().next().map(String::from).unwrap_or_default();
    (debrace(&last).to_string(), initial)
}

fn debrace(text: &str) -> &str {
    text.trim_matches('{').trim_matches('}')
}

/// Sort label per plain.bst semantics: "Last, First" of the first author,
/// falling back to key then institution/publisher.
pub fn sort_label(entry: &Entry) -> String {
    if let Some(author) = entry.get("author") {
        let first_author = author.split(" and ").next().unwrap_or("").trim();
        if first_author == "others" {
            return "et al.".to_string();
        }
        let (last, first_initial) = parse_name(first_author);
        return format!("{last}, {first_initial}");
    }
    entry
        .get("key")
        .or_else(|| entry.get("publisher"))
        .or_else(|| entry.get("institution"))
        .unwrap_or("")
        .to_string()
}

/// Classify whether this request can be served natively.
pub fn capability(database: &Database, style: &str) -> crate::Capability {
    if style != "plain" && style != "numeric" {
        return crate::Capability::Fallback("only numeric styles supported");
    }
    const SUPPORTED: &[&str] = &["article", "book", "incollection", "inbook", "misc"];
    const SUPPORTED_FIELDS: &[&str] = &[
        "author", "title", "journal", "year", "volume", "number", "pages",
        "publisher", "address", "editor", "booktitle", "note", "month",
    ];
    for entry in &database.entries {
        if !SUPPORTED.contains(&entry.kind.as_str()) {
            return crate::Capability::Fallback("unsupported entry type");
        }
        for field in entry.fields.keys() {
            if !SUPPORTED_FIELDS.contains(&field.as_str()) {
                return crate::Capability::Fallback("unsupported field");
            }
        }
    }
    crate::Capability::Supported
}

/// Emit a numeric `thebibliography` document for the cited entries.
/// `cited` lists citation keys in first-use order.
pub fn emit_bbl(database: &Database, cited: &[String]) -> String {
    let by_key: BTreeMap<&str, &Entry> =
        database.entries.iter().map(|entry| (entry.key.as_str(), entry)).collect();

    let mut cited_entries: Vec<&Entry> =
        cited.iter().filter_map(|key| by_key.get(key.as_str()).copied()).collect();
    cited_entries.sort_by_key(|entry| sort_label(entry).to_lowercase());

    let mut output = String::from("\\begin{thebibliography}{}\n\n");
    for (index, entry) in cited_entries.iter().enumerate() {
        output.push_str(&format!("\\bibitem{{{}}}\n", entry.key));
        match format_entry(entry) {
            Some(text) => output.push_str(&text),
            None => continue,
        }
        if index + 1 < cited_entries.len() {
            output.push('\n');
        }
    }
    output.push_str("\n\\end{thebibliography}\n");
    output
}

fn format_entry(entry: &Entry) -> Option<String> {
    let author_or_editor = entry
        .get("author")
        .or(entry.get("editor"))
        .or_else(|| entry.get("publisher"))
        .map(str::to_string)
        .unwrap_or_default();
    let title = entry.get("title")?;
    let year = entry.get("year").map(str::to_string).unwrap_or_default();
    let body = match entry.kind.as_str() {
        "article" => {
            let journal = entry.get("journal")?;
            let volume = entry.get("volume").map(|v| format!(" {v}")).unwrap_or_default();
            let number = entry.get("number").map(|n| format!("({n})")).unwrap_or_default();
            let pages = entry.get("pages").map(|p| format!(", {p}")).unwrap_or_default();
            format!(
                "{author_or_editor}. \"{title}.\" {journal}{volume}{number}{pages} ({year})."
            )
        }
        "book" => format!("{author_or_editor}. \\emph{{{title}}}. {year}."),
        "incollection" | "inbook" => {
            let booktitle = entry.get("booktitle")?;
            format!(
                "{author_or_editor}. \"{title}.\" In \\emph{{{booktitle}}}, {year}."
            )
        }
        _ => format!("{author_or_editor}. {title}. {year}."),
    };
    Some(body)
}
