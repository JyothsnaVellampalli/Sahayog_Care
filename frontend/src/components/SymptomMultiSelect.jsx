import { useEffect, useId, useMemo, useRef, useState } from "react";
import "./SymptomMultiSelect.css";

/**
 * Accessible, searchable multi-select for symptoms.
 *
 * Follows the WAI-ARIA editable-combobox-with-listbox pattern:
 *  - the text input is role="combobox" with aria-expanded / aria-controls and
 *    aria-activedescendant pointing at the focused option,
 *  - the popup is role="listbox", each row role="option" with aria-selected,
 *  - keyboard: ArrowDown/Up move, Enter toggles, Escape closes, Home/End jump,
 *  - selected items are shown as removable chips above the input,
 *  - a visually hidden live region announces selection count changes.
 *
 * Props:
 *  - options: [{ id, label, ... }]
 *  - selectedIds: string[]
 *  - onAdd(id), onRemove(id)
 *  - label: visible field label
 *  - id: optional base id
 */
export default function SymptomMultiSelect({
  options,
  selectedIds,
  onAdd,
  onRemove,
  label = "Symptoms",
}) {
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const labelId = `${baseId}-label`;
  const hintId = `${baseId}-hint`;

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const inputRef = useRef(null);
  const listRef = useRef(null);
  const rootRef = useRef(null);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  // Options that match the query and are not already selected.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return options.filter(
      (o) =>
        !selectedSet.has(o.id) && (q === "" || o.label.toLowerCase().includes(q))
    );
  }, [options, selectedSet, query]);

  const selectedOptions = useMemo(
    () => selectedIds.map((id) => options.find((o) => o.id === id)).filter(Boolean),
    [selectedIds, options]
  );

  // Keep the active option index in range when the list changes.
  useEffect(() => {
    if (activeIndex >= filtered.length) setActiveIndex(filtered.length - 1);
  }, [filtered, activeIndex]);

  // Close the popup when focus/click leaves the component.
  useEffect(() => {
    function onDocPointerDown(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", onDocPointerDown);
    return () => document.removeEventListener("pointerdown", onDocPointerDown);
  }, []);

  function openList() {
    if (!open) {
      setOpen(true);
      setActiveIndex(filtered.length ? 0 : -1);
    }
  }

  function selectOption(option) {
    if (!option) return;
    onAdd(option.id);
    setQuery("");
    // Keep the list open so several symptoms can be added in a row.
    setActiveIndex(0);
    inputRef.current?.focus();
  }

  function handleKeyDown(e) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        openList();
        setActiveIndex((i) => open ? Math.min(i + 1, filtered.length - 1) : (filtered.length ? 0 : -1));
        break;
      case "ArrowUp":
        e.preventDefault();
        openList();
        setActiveIndex((i) => open ? Math.max(i - 1, 0) : filtered.length - 1);
        break;
      case "Home":
        if (open) {
          e.preventDefault();
          setActiveIndex(0);
        }
        break;
      case "End":
        if (open) {
          e.preventDefault();
          setActiveIndex(filtered.length - 1);
        }
        break;
      case "Enter":
        if (open && activeIndex >= 0 && filtered[activeIndex]) {
          e.preventDefault();
          selectOption(filtered[activeIndex]);
        }
        break;
      case "Escape":
        if (open) {
          e.preventDefault();
          setOpen(false);
        }
        break;
      case "Backspace":
        // Remove the last chip when the query is empty (common UX).
        if (query === "" && selectedOptions.length > 0) {
          onRemove(selectedOptions[selectedOptions.length - 1].id);
        }
        break;
      default:
        break;
    }
  }

  // Scroll the active option into view as the user navigates.
  useEffect(() => {
    if (!open || activeIndex < 0) return;
    const el = listRef.current?.querySelector(`[data-index="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, open]);

  const activeId =
    open && activeIndex >= 0 && filtered[activeIndex]
      ? `${baseId}-opt-${filtered[activeIndex].id}`
      : undefined;

  return (
    <div className="sms" ref={rootRef} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
      <span className="sms__label" id={labelId}>
        {label}
      </span>

      <div className="sms__selection">
      {/* Selected chips */}
      {selectedOptions.length > 0 && (
        <ul className="sms__chips" aria-label="Selected symptoms">
          {selectedOptions.map((o) => (
            <li key={o.id} className="sms__chip">
              <span className="sms__chip-label">{o.label}</span>
              <button
                type="button"
                className="sms__chip-remove"
                onClick={() => onRemove(o.id)}
                aria-label={`Remove ${o.label}`}
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Combobox input */}
      <div className="sms__field">
        <input
          ref={inputRef}
          type="text"
          className="sms__input"
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listboxId : undefined}
          aria-labelledby={labelId}
          aria-describedby={hintId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          autoComplete="off"
          placeholder="Select your symptoms…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIndex(0);
            openList();
          }}
          onFocus={openList}
          onClick={openList}
          onKeyDown={handleKeyDown}
        />
      </div>

      </div>
      <p className="sms__hint" id={hintId}>
        Type to search, use arrow keys to browse, Enter to add.
      </p>

      {/* Listbox popup */}
      {open && (
        <ul
          ref={listRef}
          className="sms__listbox"
          role="listbox"
          id={listboxId}
          aria-labelledby={labelId}
        >
          {filtered.length === 0 ? (
            <li className="sms__empty" role="option" aria-selected={false} aria-disabled="true">
              {query ? "No matching symptoms" : "All symptoms added"}
            </li>
          ) : (
            filtered.map((o, index) => (
              <li
                key={o.id}
                id={`${baseId}-opt-${o.id}`}
                data-index={index}
                className={
                  "sms__option" +
                  (index === activeIndex ? " sms__option--active" : "")
                }
                role="option"
                aria-selected={false}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(e) => {
                  // Prevent the input from losing focus before we handle click.
                  e.preventDefault();
                  selectOption(o);
                }}
              >
                {o.label}
              </li>
            ))
          )}
        </ul>
      )}

      {/* Live region: announces selection count to screen readers */}
      <span className="sr-only" aria-live="polite">
        {selectedOptions.length} symptom
        {selectedOptions.length === 1 ? "" : "s"} selected
      </span>
    </div>
  );
}
