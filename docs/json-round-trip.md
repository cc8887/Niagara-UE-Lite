# Native Niagara JSON documents

Current native asset, edit and rendering evidence is recorded in
[json-round-trip-validation.md](json-round-trip-validation.md).

The preview.6 CLI adds `export` and `import` for `ue-niagara-document/1`.
Unlike the inspection Snapshot, this document contains the native object graph
needed to recreate an uncooked System or Emitter in a separate workspace.
It is not included in the previously published preview.5 package.

```sh
./niagara-cli --workspace source export --asset /Game/Effects/MySystem --out transfer/effect.json
./niagara-cli --workspace restored import --file transfer/effect.json
./niagara-cli --workspace restored read --asset /Game/Effects/MySystem
./niagara-cli --workspace restored cook --asset /Game/Effects/MySystem --package outputs/runtime
./niagara-cli render --asset /Game/Effects/MySystem --package outputs/runtime --out outputs/frame.png
```

Windows uses `niagara-cli.exe`. The destination workspace is initialized from the
kit. Import preserves original `/Game` package paths and refuses existing target
packages or resource files; relocation and overwrite are not part of this format.

## Representation

| Field | Purpose |
| --- | --- |
| `engine` | Exact UE build; a different build is rejected |
| `packages` | Root and project Niagara dependency packages, persistent GUIDs and package metadata |
| `objects` | Class, stable path, Outer, archetype and relevant object flags |
| `properties` | Named nontransient reflected properties, their C++ types and native text values |
| `graph` | Node GUID, pin types, defaults and connections, checked against the restored native pin graph |
| `references` | Object references used to retain the serialized object closure |
| `nativeData` | Base64 per-object UE archive, including custom serialization not covered by reflected properties |
| `nativeSha256`, `customVersions` | Native archive integrity and serializer version context |
| `externalReferences` | References outside the document's Niagara object packages |
| `resources` | Relative file paths, lengths and SHA256 for resource attachments |

This is deliberately a hybrid representation: readable properties and pin graphs
plus native object extensions. It is not a Base64 wrapper around a complete
`.uasset`, but it is also **not an entirely textual representation of every native
field**. Preserve `nativeData` verbatim. The backend invokes the native serializer;
it does not implement a replacement Niagara VM or a cross-engine renderer.

System/Emitter-owned graphs, Scratch Pad scripts, node layout/comments, nested
inputs, Rapid Iteration data, renderer configuration and editor UObject state
are retained by the object archive. Referenced project Niagara Systems, Emitters
and Scripts enter the same object table, including parent emitter assets and
inherited snapshots. Engine/plugin dependencies still require matching content
and classes in the destination kit.

Non-Niagara project assets such as materials, textures and meshes are copied into
`effect.json.assets/`, including available package sidecars. Their package
dependency closure is traversed. Transfer that directory alongside the JSON.
The resource manifest contains relative paths, not the export machine's paths.
These resources remain native assets; this does not expose their full editing
formats as Niagara JSON or guarantee external source-art reimport availability.

## Editing properties in JSON

Each property includes a native text value and an explicit `apply` flag:

```json
"NodePosX": { "type": "int32", "text": "321", "apply": true }
```

Change `text` and set `apply:true` to apply an overlay after native restoration.
Import validates the property's existence and type. It sends edit notifications,
invalidates Niagara script sources and requests compilation when overlays exist.
The next export writes the resulting native state with `apply:false`.

Object identities, native archives and the `graph` projection are not general
graph-edit commands. Editing the read-only pin projection alone is rejected.
For module insertion, parameter changes and binding operations, use the existing
native recipe API after import. Full free-form node construction from plain JSON
remains separate from restoring an existing internal graph.

## Restoration and failure behavior

1. Validate schema, paths, identities, resource hashes and native data hashes.
2. Refuse collisions; install checked resource files.
3. Create package and object identities with their Outer/archetype relationships.
4. Restore all native object data and references, then verify pin graphs.
5. Apply explicit property overlays; compile and save native packages.

The CLI removes newly installed resources and newly written Niagara packages if
the native import fails. Existing assets are not overwritten. Native failures
and unsupported/missing classes are reported rather than silently dropped.
As with native UE asset import, use documents from trusted sources; the native
extension is interpreted by matching engine serializers.

Do not manually call package `PostLoad` on constructed objects: without a linker
version context this can run legacy migrations and alter metadata. The importer
uses the current-build archive and native compilation instead.

## Acceptance boundary

Editor semantics and behavior are the target, not byte-identical `.uasset` files.
Compiled shader/cache records and compiler-generated change IDs can regenerate.
The acceptance tool compares authored object identities, properties, metadata and
pin graphs, reporting its explicit compilation-derived exclusions.

`tools/acceptance_document.py` performs export, independent import, process reload,
re-export and structural comparison. `--render` adds paired native Cook/render.
If decoded pixels differ, it runs two additional controls on each original and
restored runtime. Counts must match; pixel differences must fit the reported
repeat-render envelope. A tolerance pass is reported separately from exact PNG
identity. `tools/acceptance_document_edits.py` verifies real JSON edits, failure
rejection, collision handling and resource rollback.

The format does not promise cross-version migration, arbitrary missing-plugin
recovery, restoration of an editor session's unsaved undo history, or equivalent
world-dependent behavior without the required world/components. Cross-platform
portability of a native extension needs explicit qualification; matching build
strings alone should not be treated as that evidence.
