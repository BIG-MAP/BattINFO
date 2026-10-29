"use client";

// One recursive component renders every record type. It asks the schema what
// may go here and shows only what is present plus a "+" offering the rest, so
// a schema of several hundred fields stays a short list.
//
// Order rule: what cannot collapse, then choices that can, then ordinary
// sections. A choice about this node sits between its values and its parts.
//
// Errors are not re-derived here. Every row asks the validator's own issue list
// what is wrong at its path, so pattern, format, length and the anyOf rules all
// surface without this file knowing any of them.
//
// How a row looks is ui.tsx; which input a value gets is controls.tsx.

import { useState } from "react";
import { blankFor, controlFor, fieldsOf, isDeprecated, join, requiredGroups, type Field, type Located } from "./schema";
import { Leaf } from "./controls";
import { AddField, Branch, LABEL, LEAF_ROW, Label, TITLE, ValueRow } from "./ui";
import { PROPERTY_LIST } from "./vocab";

type Obj = Record<string, unknown>;

/** Dotted paths as lib/validate.ts reports them: "cell_spec.id", "notes.0". */
type Issues = Map<string, string[]>;

/** A control that holds other rows rather than a value of its own. */
function isContainer(kind: string): boolean {
  return kind === "object" || kind === "map" || kind === "array";
}

function withKey(obj: Obj, key: string, value: unknown): Obj {
  return { ...obj, [key]: value };
}

function withoutKey(obj: Obj, key: string): Obj {
  const next = { ...obj };
  delete next[key];
  return next;
}

function isEmpty(value: unknown): boolean {
  return value === undefined || value === "";
}

/** Whether anything is wrong at this path or beneath it, so a collapsed branch
 *  can say it is hiding something.
 *
 *  A mark rather than a count, deliberately. The validator reports a message
 *  per failed branch of a `oneOf`, and reports missing properties the tree
 *  shows no row for -- so a number sent the reader hunting for fields that
 *  were not there. The rows inside carry what is actually wrong; this only
 *  says to look. */
function anythingUnder(issues: Issues, path: string): boolean {
  for (const at of issues.keys()) {
    if (at === path || at.startsWith(`${path}.`)) return true;
  }
  return false;
}

/** What every node in the tree is handed. */
interface TreeProps {
  path: string;
  /** How many headings enclose this node, which is where an open section
   *  parks itself. Counts headings on screen, not keys in the record: a list
   *  item is a heading, so its contents are two in from the list. */
  depth: number;
  issues: Issues;
  omit?: string[];
}

function ArrayBranch({
  field,
  title,
  value,
  onChange,
  onRemove,
  startOpen,
  path,
  depth,
  issues,
  omit,
}: TreeProps & {
  field: Field;
  title?: React.ReactNode;
  value: unknown[];
  onChange: (next: unknown[]) => void;
  onRemove?: () => void;
  startOpen?: boolean;
}) {
  // Indexes added on this screen, which are the only ones that open by
  // themselves.
  const [added, setAdded] = useState<number[]>([]);
  const control = controlFor(field.loc);
  if (control.kind !== "array") return null;
  const itemIsObject = controlFor(control.items).kind === "object";
  const replace = (index: number, next: unknown) => onChange(value.map((item, i) => (i === index ? next : item)));
  const drop = (index: number) => onChange(value.filter((_, i) => i !== index));

  return (
    <Branch
      title={title ?? field.label}
      help={field.help}
      note={value.length ? `${value.length} item${value.length === 1 ? "" : "s"}` : undefined}
      problems={anythingUnder(issues, path)}
      startOpen={startOpen}
      level={depth}
      onRemove={onRemove}
    >
      {value.map((item, index) => {
        const itemPath = join(path, index);
        const problem = issues.get(itemPath)?.[0];
        return itemIsObject ? (
          // An item added here was asked for, so it opens. One that arrived
          // with the record was not, and opening every one of them is how a
          // loaded record became a wall.
          <Branch
            key={index}
            title={index + 1}
            problems={anythingUnder(issues, itemPath)}
            startOpen={added.includes(index)}
            level={depth + 1}
            onRemove={() => drop(index)}
          >
            <ObjectNode
              loc={control.items}
              value={(item ?? {}) as Obj}
              onChange={(next) => replace(index, next)}
              path={itemPath}
              // Two in, not one: the numbered item is a heading of its own.
              depth={depth + 2}
              issues={issues}
              omit={omit}
            />
          </Branch>
        ) : (
          <ValueRow
            key={index}
            label={<span className={`${LABEL} tabular-nums`}>{index + 1}</span>}
            onRemove={() => drop(index)}
            problem={problem}
          >
            <Leaf
              field={{ ...field, label: `${field.label} ${index + 1}`, loc: control.items }}
              value={item}
              onChange={(next) => replace(index, next)}
              flagged={!!problem}
            />
          </ValueRow>
        );
      })}
      <button
        type="button"
        onClick={() => {
          setAdded((indexes) => [...indexes, value.length]);
          onChange([...value, blankFor(control.items)]);
        }}
        className="flex items-center gap-1.5 py-1.5 text-sm text-brandtext"
      >
        <span className="w-3 shrink-0 text-center">+</span>
        add item
      </button>
    </Branch>
  );
}

// A named map: the keys are the author's (a property called "diameter", say, or
// a protocol condition), the values all share one schema. It is a container
// like an object, but the schema cannot list what is in it, so the form asks
// for the name too.
function MapBranch({
  field,
  title,
  value,
  onChange,
  onRemove,
  startOpen,
  path,
  depth,
  issues,
  omit,
}: TreeProps & {
  field: Field;
  title?: React.ReactNode;
  value: Obj;
  onChange: (next: Obj) => void;
  onRemove?: () => void;
  startOpen?: boolean;
}) {
  const [name, setName] = useState("");
  const [added, setAdded] = useState<string[]>([]);
  const control = controlFor(field.loc);
  if (control.kind !== "map") return null;
  const values = control.values;
  const pattern = control.keyPattern ?? ".";

  const entries = Object.entries(value);
  // An entry that is itself a container gets its own section; a plain value
  // gets a row.
  const entryKind = controlFor(values).kind;
  const nested = entryKind === "object" || entryKind === "map";
  const legal = name !== "" && !(name in value) && new RegExp(pattern).test(name);

  function add() {
    if (!legal) return;
    setAdded((keys) => [...keys, name]);
    onChange({ ...value, [name]: blankFor(values) as Obj });
    setName("");
  }

  function drop(key: string) {
    onChange(withoutKey(value, key));
  }

  return (
    <Branch
      title={title ?? field.label}
      help={field.help}
      note={entries.length ? `${entries.length} entr${entries.length === 1 ? "y" : "ies"}` : undefined}
      problems={anythingUnder(issues, path)}
      startOpen={startOpen}
      level={depth}
      onRemove={onRemove}
    >
      {entries.map(([key, item]) => {
        const here = join(path, key);
        return nested ? (
          <Branch
            key={key}
            title={key}
            problems={anythingUnder(issues, here)}
            startOpen={added.includes(key)}
            level={depth + 1}
            onRemove={() => drop(key)}
          >
            <ObjectNode
              loc={values}
              value={(item ?? {}) as Obj}
              onChange={(next) => onChange({ ...value, [key]: next })}
              path={here}
              // Two in, not one: the entry is a heading of its own.
              depth={depth + 2}
              issues={issues}
              omit={omit}
            />
          </Branch>
        ) : (
          <ValueRow
            key={key}
            label={<span className={LABEL}>{key}</span>}
            onRemove={() => drop(key)}
            problem={issues.get(here)?.[0]}
          >
            <Leaf
              field={{ ...field, label: key, loc: values }}
              value={item}
              onChange={(next) => onChange({ ...value, [key]: next })}
              flagged={issues.has(here)}
            />
          </ValueRow>
        );
      })}

      <div className={LEAF_ROW}>
        <span className="w-3 shrink-0 text-center text-sm text-brandtext">+</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="name"
          aria-label={`Name of a new ${field.label} entry`}
          list={PROPERTY_LIST}
          className={`${LABEL} rounded border border-border bg-surface/60 px-2 py-0.5 text-ink focus:border-brand-500 focus:outline-none`}
        />
        <button
          type="button"
          onClick={add}
          disabled={!legal}
          className={`text-sm ${legal ? "text-brandtext" : "cursor-not-allowed text-ink-faint/40"}`}
        >
          add
        </button>
        <span className="flex-1" />
      </div>
    </Branch>
  );
}

/** A field plus the one control lookup every decision below needs. */
interface Row {
  field: Field;
  kind: string;
}

export function ObjectNode({
  loc,
  value,
  onChange,
  path = "",
  depth = 0,
  issues,
  omit,
}: Partial<TreeProps> & {
  loc: Located;
  value: Obj;
  onChange: (next: Obj) => void;
  issues: Issues;
  /** Dotted paths the page settles itself -- what it stamps in, and the
   *  identity the library derives on save. Matched against the row's full
   *  path, so it reaches into the record body and not merely the top level. */
  omit?: string[];
}) {
  // Branches a reader has just asked for start open even when they sit deeper
  // than the one level shown by default.
  const [opened, setOpened] = useState<string[]>([]);

  // One control lookup per field, reused by every decision below. A value the
  // schema fixes (`const`) is already set and not worth a row.
  const rows: Row[] = fieldsOf(loc, value)
    .filter((field) => !omit?.includes(join(path, field.key)))
    .map((field) => ({ field, kind: controlFor(field.loc, value[field.key]).kind }))
    .filter((row) => row.kind !== "const");
  const byKey = (key: string) => rows.find((row) => row.field.key === key);

  // A choice the schema states as "one of these": the row is the choice, so its
  // label is a selector rather than a name. The member on show is owned by that
  // row; any further members the record also carries stay ordinary rows, so
  // nothing a record holds is ever hidden.
  //
  // Members this node cannot render are dropped first. A required-group may
  // name a key that is not an editable property here -- a value the schema
  // fixes, or one declared in a branch rather than in `properties` -- and a
  // selector option resolving to no field would crash the row rather than fill
  // it. No schema does that today; twenty-two record types is not the place to
  // rely on it.
  const groups = requiredGroups(loc, value)
    .map((keys) => keys.filter(byKey))
    .filter((keys) => keys.length > 1)
    .map((keys) => {
      const chosen = keys.find((key) => key in value);
      return { keys, chosen, collapsible: isContainer(chosen ? byKey(chosen)!.kind : "") };
    });
  const owned = new Set(groups.map((group) => group.chosen).filter(Boolean) as string[]);

  const shown = rows.filter(
    (row) => (row.field.required || row.field.key in value) && !owned.has(row.field.key),
  );
  const leaves = shown.filter((row) => !isContainer(row.kind));
  const branches = shown.filter((row) => isContainer(row.kind));
  // Nothing the author does not own, and nothing the schemas have moved off,
  // is offered: an opaque value and a deprecated spelling both show when a
  // loaded record carries one and are never conjured from the "add" list.
  const addable = rows.filter(
    (row) => !(row.field.key in value) && row.kind !== "opaque" && !isDeprecated(row.field),
  );

  function add(row: Row) {
    onChange(withKey(value, row.field.key, blankFor(row.field.loc)));
    if (isContainer(row.kind)) setOpened((keys) => [...keys, row.field.key]);
  }

  /** Switching the selector moves the row to another member of its group. */
  function choose(keys: string[], nextKey: string) {
    const current = keys.find((key) => key in value);
    const without = current ? withoutKey(value, current) : { ...value };
    const row = nextKey ? byKey(nextKey) : undefined;
    onChange(row ? withKey(without, row.field.key, blankFor(row.field.loc)) : without);
  }

  function renderGroup(group: (typeof groups)[number]) {
    const row = group.chosen ? byKey(group.chosen) : undefined;
    const field = row?.field;
    const here = field ? join(path, field.key) : "";
    const current = field ? value[field.key] : undefined;
    const problem = field ? issues.get(here)?.[0] : undefined;
    const awaited = !field || (isEmpty(current) && !!problem);
    const set = (next: unknown) => (field ? onChange(withKey(value, field.key, next)) : undefined);
    const nested: TreeProps = { path: here, depth, issues, omit };

    // The selector IS the row's name, so it goes wherever a label would -- and
    // when it names a section it carries a heading's weight.
    const selector = (
      <select
        value={group.chosen ?? ""}
        onChange={(e) => choose(group.keys, e.target.value)}
        title="Which of these the record states"
        aria-label="Which of these the record states"
        className={`${group.collapsible ? TITLE : LABEL} rounded border border-transparent bg-transparent py-0.5 hover:border-border focus:border-brand-500 focus:outline-none`}
      >
        <option value="">choose…</option>
        {group.keys.map((key) => (
          <option key={key} value={key}>
            {byKey(key)?.field.label ?? key}
          </option>
        ))}
      </select>
    );

    // A member of the group can be a whole object or a list, not just a value
    // -- an electrode is "one of spec id, coating, current collector,
    // property", and three of those are objects. Such a choice opens as a
    // section under the selector rather than being forced into a text box.
    if (row && field && group.collapsible) {
      const shared = { key: group.keys.join(), field, title: selector, onRemove: () => choose(group.keys, ""), startOpen: true };
      if (row.kind === "map") {
        return <MapBranch {...shared} {...nested} value={(current ?? {}) as Obj} onChange={set as (next: Obj) => void} />;
      }
      if (row.kind === "array") {
        return <ArrayBranch {...shared} {...nested} value={(current ?? []) as unknown[]} onChange={set} />;
      }
      return (
        <Branch
          key={shared.key}
          title={selector}
          help={field.help}
          problems={anythingUnder(issues, here)}
          startOpen
          level={depth}
          onRemove={shared.onRemove}
        >
          <ObjectNode loc={field.loc} value={(current ?? {}) as Obj} onChange={set} {...nested} depth={depth + 1} />
        </Branch>
      );
    }

    return (
      <ValueRow
        key={group.keys.join()}
        label={selector}
        help={field?.help}
        onRemove={group.chosen ? () => choose(group.keys, "") : undefined}
        wanted={awaited}
        problem={awaited ? undefined : problem}
      >
        {field ? (
          <Leaf field={field} value={current} onChange={set} flagged={awaited} />
        ) : (
          <p className="px-2 py-1 text-xs text-ink-faint/60">choose one on the left</p>
        )}
      </ValueRow>
    );
  }

  function renderField({ field, kind }: Row) {
    const here = join(path, field.key);
    const set = (next: unknown) => onChange(withKey(value, field.key, next));
    const remove = field.required ? undefined : () => onChange(withoutKey(value, field.key));
    // Everything arrives shut. A detailed cell spec opens eight sections and
    // several hundred rows at once otherwise, which is a wall rather than a
    // form; the section headings say what is inside and what still needs
    // filling, so the shape of the record is readable without any of it open.
    // A section asked for by name is the exception -- see `add`.
    const startOpen = opened.includes(field.key);
    const nested: TreeProps = { path: here, depth, issues, omit };

    if (kind === "object") {
      return (
        <Branch
          key={field.key}
          title={field.label}
          help={field.help}
          problems={anythingUnder(issues, here)}
          startOpen={startOpen}
          level={depth}
          onRemove={remove}
        >
          <ObjectNode
            loc={field.loc}
            value={(value[field.key] ?? {}) as Obj}
            onChange={set}
            {...nested}
            depth={depth + 1}
          />
        </Branch>
      );
    }

    if (kind === "map") {
      return (
        <MapBranch
          key={field.key}
          field={field}
          value={(value[field.key] ?? {}) as Obj}
          onChange={set as (next: Obj) => void}
          onRemove={remove}
          startOpen={startOpen}
          {...nested}
        />
      );
    }

    if (kind === "array") {
      return (
        <ArrayBranch
          key={field.key}
          field={field}
          value={(value[field.key] ?? []) as unknown[]}
          onChange={set}
          onRemove={remove}
          startOpen={startOpen}
          {...nested}
        />
      );
    }

    // An empty box that something is waiting on says so in one word. The
    // validator's own sentence is kept for a value that is present but wrong,
    // where the reason actually needs explaining.
    const current = value[field.key];
    const problem = issues.get(here)?.[0];
    const awaited = isEmpty(current) && (field.required || !!problem);
    return (
      <ValueRow
        key={field.key}
        label={<Label text={field.label} />}
        help={field.help}
        onRemove={remove}
        wanted={awaited}
        problem={awaited ? undefined : problem}
      >
        <Leaf field={field} value={current} onChange={set} flagged={awaited || !!problem} />
      </ValueRow>
    );
  }

  return (
    <div>
      {leaves.map(renderField)}
      {groups.filter((group) => !group.collapsible).map(renderGroup)}
      {groups.filter((group) => group.collapsible).map(renderGroup)}
      {branches.map(renderField)}
      <AddField options={addable.map((row) => row.field)} onAdd={(field) => add(byKey(field.key)!)} />
    </div>
  );
}
