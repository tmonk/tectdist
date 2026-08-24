//! `.bib` database parser for the bounded common subset (plan X6.2).
//!
//! Handles balanced-brace and quoted values, `@string` abbreviation (with
//! `#` concatenation), `@comment`/`@preamble`, month macros, and the entry
//! types used by the numeric subset. Unknown entry types are kept with their
//! fields so the capability layer can decide fallback instead of failing.

use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub kind: String,
    pub key: String,
    pub fields: BTreeMap<String, String>,
}

impl Entry {
    pub fn get(&self, field: &str) -> Option<&str> {
        self.fields.get(field).map(String::as_str)
    }
}

#[derive(Debug, Default)]
pub struct Database {
    pub entries: Vec<Entry>,
    strings: BTreeMap<String, String>,
}

const MONTH_MACROS: &[(&str, &str)] = &[
    ("jan", "January"), ("feb", "February"), ("mar", "March"), ("apr", "April"),
    ("may", "May"), ("jun", "June"), ("jul", "July"), ("aug", "August"),
    ("sep", "September"), ("oct", "October"), ("nov", "November"), ("dec", "December"),
];

pub fn parse(input: &str) -> Result<Database, String> {
    let mut database = Database {
        strings: BTreeMap::new(),
        entries: Vec::new(),
    };
    for (name, expansion) in MONTH_MACROS {
        database.strings.insert((*name).to_string(), (*expansion).to_string());
    }
    let chars: Vec<char> = input.chars().collect();
    let mut position = 0;
    while position < chars.len() {
        if chars[position] == '@' {
            position += 1;
            let start = position;
            while position < chars.len() && chars[position].is_alphanumeric() {
                position += 1;
            }
            let kind: String = chars[start..position].iter().collect::<String>().to_lowercase();
            while position < chars.len() && chars[position].is_whitespace() {
                position += 1;
            }
            let open = *chars.get(position).ok_or_else(|| {
                format!("entry '{kind}' at char {start}: unexpected end after @")
            })?;
            if open != '{' && open != '(' {
                return Err(format!("entry '{kind}' at char {start}: expected '{{' or '('"));
            }
            let close = if open == '{' { '}' } else { ')' };
            let body = read_balanced(&chars, &mut position, open, close)?;
            match kind.as_str() {
                "comment" => {}
                "preamble" => {}
                "string" => {
                    let (field, value) =
                        split_field(&body).ok_or("@string entry missing '='")?;
                    database
                        .strings
                        .insert(field.to_lowercase(), expand(value.trim(), &database.strings));
                }
                _ => {
                    let (key, fields_text) = split_key(&body);
                    let mut fields = BTreeMap::new();
                    for field in split_top_level_commas(fields_text) {
                        if let Some((name, value)) = split_field(&field) {
                            fields
                                .insert(name.to_lowercase(), expand(value.trim(), &database.strings));
                        }
                    }
                    database.entries.push(Entry { kind, key, fields });
                }
            }
        } else {
            position += 1;
        }
    }
    Ok(database)
}

/// Read a balanced `{...}` or `(...)` group starting at the delimiter,
/// honouring quote characters and brace nesting inside values.
fn read_balanced(
    chars: &[char],
    position: &mut usize,
    open: char,
    close: char,
) -> Result<String, String> {
    debug_assert_eq!(chars[*position], open);
    *position += 1;
    let start = *position;
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut in_quotes = false;
    while *position < chars.len() {
        let character = chars[*position];
        if in_quotes {
            if character == '"' {
                in_quotes = false;
            }
        } else {
            match character {
                '"' => in_quotes = true,
                '{' => brace_depth += 1,
                '}' => {
                    if open == '{' && brace_depth == 0 && paren_depth == 0 {
                        let body: String = chars[start..*position].iter().collect();
                        *position += 1;
                        return Ok(body);
                    }
                    brace_depth = brace_depth.saturating_sub(1);
                }
                '(' if close == ')' => paren_depth += 1,
                ')' if close == ')' => {
                    if paren_depth == 0 {
                        let body: String = chars[start..*position].iter().collect();
                        *position += 1;
                        return Ok(body);
                    }
                    paren_depth -= 1;
                }
                _ => {}
            }
        }
        *position += 1;
    }
    Err("unterminated entry".to_string())
}

fn split_key(body: &str) -> (String, &str) {
    match find_top_level(body, ',') {
        Some(index) => (body[..index].trim().to_string(), &body[index + 1..]),
        None => (body.trim().to_string(), ""),
    }
}

/// Find a character at brace/paren/quote nesting depth zero.
fn find_top_level(text: &str, needle: char) -> Option<usize> {
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut in_quotes = false;
    for (index, character) in text.char_indices() {
        if in_quotes {
            if character == '"' {
                in_quotes = false;
            }
            continue;
        }
        match character {
            '"' => in_quotes = true,
            '{' => brace_depth += 1,
            '}' => brace_depth = brace_depth.saturating_sub(1),
            '(' => paren_depth += 1,
            ')' => paren_depth -= 1,
            c if c == needle && brace_depth == 0 && paren_depth == 0 => return Some(index),
            _ => {}
        }
    }
    None
}

fn split_top_level_commas(text: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut rest = text;
    loop {
        match find_top_level(rest, ',') {
            Some(index) => {
                parts.push(rest[..index].to_string());
                rest = &rest[index + 1..];
            }
            None => {
                parts.push(rest.to_string());
                break;
            }
        }
    }
    parts
}

fn split_field(field: &str) -> Option<(&str, &str)> {
    let index = find_top_level(field, '=')?;
    let (name, value) = field.split_at(index);
    Some((name.trim(), value[1..].trim()))
}

/// Expand `#` concatenation, quoted/braced values, and @string references.
fn expand(text: &str, strings: &BTreeMap<String, String>) -> String {
    let mut output = String::new();
    for part in split_concatenation(text) {
        let trimmed = part.trim();
        if trimmed.starts_with('"') && trimmed.ends_with('"') && trimmed.len() >= 2 {
            // Interior whitespace is significant; only the quotes come off.
            output.push_str(&trimmed[1..trimmed.len() - 1]);
        } else if trimmed.starts_with('{') && trimmed.ends_with('}') {
            output.push_str(&trimmed[1..trimmed.len() - 1]);
        } else if let Some(value) = strings.get(&trimmed.to_lowercase()) {
            output.push_str(value);
        } else {
            output.push_str(trimmed);
        }
    }
    output
}

fn split_concatenation(text: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut brace_depth = 0usize;
    let mut in_quotes = false;
    for character in text.chars() {
        match character {
            '{' => {
                brace_depth += 1;
                current.push(character);
            }
            '}' => {
                brace_depth = brace_depth.saturating_sub(1);
                current.push(character);
            }
            '"' => {
                in_quotes = !in_quotes;
                current.push(character);
            }
            '#' if brace_depth == 0 && !in_quotes => {
                parts.push(std::mem::take(&mut current));
            }
            _ => current.push(character),
        }
    }
    parts.push(current);
    parts
}
