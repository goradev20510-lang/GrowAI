"use client";

import clsx from "clsx";
import * as Tabs from "@radix-ui/react-tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { FileArrowUp } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { fmtTs } from "@/lib/format";
import { Button, Field, Mono, PageHead, SectionHead, Table, inputCls } from "@/components/ui";

type Kind = "bank" | "invoice" | "remittance";

const KINDS: { value: Kind; label: string; accept: string[]; note: string }[] = [
  { value: "bank", label: "Bank statement", accept: [".csv", ".xlsx", ".xls"], note: "CSV or Excel. Columns are parsed directly, with no model involved." },
  { value: "invoice", label: "Invoices", accept: [".pdf", ".csv", ".xlsx", ".xls"], note: "PDF, CSV or Excel register. Spreadsheets are parsed directly; PDF text is structured (by the model when one is configured) and validated before it is saved." },
  { value: "remittance", label: "Remittance advice", accept: [".eml", ".txt", ".pdf"], note: "A payment email or pasted text. Invoice references, amounts, TDS and UTR are extracted, and the sentence each value came from is kept as evidence." },
];

export default function ImportPage() {
  return (
    <>
      <PageHead title="Import." lede="Bring in the three sources reconciliation needs. Re-uploading the same file is detected and skipped." />
      <Tabs.Root defaultValue="bank">
        <Tabs.List className="flex gap-1 border-b border-line" aria-label="Document type">
          {KINDS.map((k) => (
            <Tabs.Trigger key={k.value} value={k.value}
              className="relative -mb-px cursor-pointer border-b border-transparent px-4 pb-3.5 pt-1 text-[14px] text-fg-3 transition-colors hover:text-fg data-[state=active]:border-fg data-[state=active]:text-fg">
              {k.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {KINDS.map((k) => (
          <Tabs.Content key={k.value} value={k.value} className="pt-8 focus-visible:outline-none">
            <Uploader kind={k.value} accept={k.accept} note={k.note} />
          </Tabs.Content>
        ))}
      </Tabs.Root>
      <Documents />
    </>
  );
}

function Uploader({ kind, accept, note }: { kind: Kind; accept: string[]; note: string }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [bank, setBank] = useState("AXIS Bank");
  const [text, setText] = useState("");
  const [extracted, setExtracted] = useState<unknown>(null);
  const dz = useDropzone({
    multiple: false,
    onDrop: (f) => {
      const ok = f[0] && accept.some((e) => f[0].name.toLowerCase().endsWith(e));
      if (f[0] && !ok) toast.error(`That file type isn't accepted here. Use ${accept.join(", ")}.`);
      else if (f[0]) setFile(f[0]);
    },
  });

  const m = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      if (kind === "bank") form.append("bank_name", bank);
      if (kind === "remittance" && !file) form.append("text", text);
      return api.importFile(kind, form);
    },
    onSuccess: (r) => {
      if (r.success) {
        const n = kind === "bank" ? `${r.transactions_imported ?? 0} credit lines` : kind === "invoice" ? `${r.invoices_imported ?? 0} invoice(s)` : "Remittance";
        toast.success(kind === "remittance" ? "Remittance extracted." : `Imported ${n}.`);
        setExtracted(r.extracted ?? null);
        setFile(null);
        setText("");
        qc.invalidateQueries();
      } else if (r.duplicate_file) toast.info(r.reason ?? "This file was already imported.");
      else toast.error(r.reason ?? "Import failed.");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div className="flex flex-col gap-5">
        <div {...dz.getRootProps()}
          className={clsx("card grain relative grid min-h-[240px] cursor-pointer place-items-center overflow-hidden border-dashed p-10 text-center transition-colors duration-200",
            dz.isDragActive ? "border-ice/70 bg-ice/[0.04]" : "hover:border-line-3")}>
          <input {...dz.getInputProps()} />
          <div>
            <FileArrowUp weight="thin" className={clsx("mx-auto size-12 transition-transform duration-500 ease-[var(--ease-out-expo)]", dz.isDragActive ? "-translate-y-1 text-ice" : "text-fg-3")} />
            <p className="mt-4 font-display text-[1.35rem] tracking-[-0.02em]">{file ? file.name : dz.isDragActive ? "Drop it." : "Drop a file, or click to choose."}</p>
            <p className="mt-2 text-[13px] text-fg-3">{file ? `${(file.size / 1024).toFixed(1)} KB` : accept.join("  ·  ")}</p>
          </div>
        </div>
        {kind === "remittance" && (
          <Field label="Or paste the email">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6}
              placeholder={"From: accounts@customer.example\nSubject: Payment against INV-005 …"}
              className={clsx(inputCls, "h-auto py-3 font-mono text-[13px] leading-relaxed")} />
          </Field>
        )}
      </div>
      <div className="flex flex-col gap-5">
        <p className="text-[14.5px] leading-relaxed text-fg-2">{note}</p>
        {kind === "bank" && <Field label="Bank"><input value={bank} onChange={(e) => setBank(e.target.value)} className={inputCls} /></Field>}
        <div><Button variant="primary" arrow disabled={!file && !(kind === "remittance" && text.trim())} loading={m.isPending} onClick={() => m.mutate()}>
          Import {kind === "bank" ? "statement" : kind === "invoice" ? "invoices" : "remittance"}
        </Button></div>
        {extracted != null && (
          <details className="card px-5 py-4 text-[13px]">
            <summary className="cursor-pointer font-medium">Extracted fields</summary>
            <pre className="mt-3 overflow-auto font-mono text-[12px] leading-relaxed text-fg-2">{JSON.stringify(extracted, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

function Documents() {
  const q = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  return (
    <>
      <SectionHead title="Imported documents." />
      <Table rows={q.data ?? []} rowKey={(d) => d.document_id} max={480} empty="Nothing imported yet." cols={[
        { key: "u", head: "Uploaded", cell: (d) => <span className="text-fg-2">{fmtTs(d.upload_time)}</span> },
        { key: "f", head: "File", cell: (d) => d.filename },
        { key: "t", head: "Type", cell: (d) => <span className="capitalize text-fg-2">{(d.document_type ?? "unknown").replaceAll("_", " ")}</span> },
        { key: "i", head: "Document", cell: (d) => <Mono>{d.document_id}</Mono>, className: "max-md:hidden" },
      ]} />
    </>
  );
}
