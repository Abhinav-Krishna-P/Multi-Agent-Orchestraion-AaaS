import { FileText, Loader2, Plus, Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/StatusBadge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useAddDocument, useDeleteDocument, useDocuments, useUpdateAgent } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { StepFooter } from './StepFooter'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_PASTE = 1000
const MAX_TITLE = 100
const TYPE_LABELS = { pdf: 'PDF', txt: 'Text file', paste: 'Pasted text' }

const ANSWER_MODES = [
  {
    strict: true,
    title: 'Only from my documents',
    description: "If the documents don't have the answer, the agent says so.",
  },
  {
    strict: false,
    title: 'Documents first, then general knowledge',
    description:
      "If the documents don't have the answer, the agent answers from what the AI already knows, and says it isn't from your documents.",
  },
]

const SEARCH_MODES = [
  { key: 'hybrid', title: 'Hybrid', note: 'Recommended', description: 'Matches by meaning and by exact words. Best for most documents.' },
  { key: 'semantic', title: 'Semantic', description: 'Matches by meaning, even when the wording differs.' },
  { key: 'keyword', title: 'Keyword', description: 'Matches exact words, such as names, codes and part numbers.' },
]

function PasteTextDialog({ open, onOpenChange, addDocument }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState(null)
  const tooLong = text.length > MAX_PASTE

  function submit(event) {
    event.preventDefault()
    setError(null)
    const form = new FormData()
    form.append('title', title.trim())
    form.append('text', text)
    addDocument.mutate(form, {
      onSuccess: () => {
        setTitle('')
        setText('')
        onOpenChange(false)
        toast.success('Text added')
      },
      onError: (err) => setError(err.message),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Paste text</DialogTitle>
          <DialogDescription>Add a short piece of text to this agent&apos;s knowledge base.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="paste-title">Title</Label>
            <Input
              id="paste-title"
              value={title}
              maxLength={MAX_TITLE}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Opening hours"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="paste-text">Text</Label>
            <Textarea
              id="paste-text"
              rows={8}
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-invalid={tooLong ? true : undefined}
              aria-describedby="paste-count"
              className="max-h-72"
            />
            <p id="paste-count" className={cn('text-sm', tooLong ? 'text-destructive' : 'text-muted-foreground')}>
              {text.length.toLocaleString()}/1,000 characters{tooLong && '. Shorten the text to add it.'}
            </p>
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={addDocument.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={addDocument.isPending || !title.trim() || !text.trim() || tooLong}>
              {addDocument.isPending && <Loader2 className="animate-spin" aria-hidden="true" />}
              Add text
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DocumentList({ agentId, documents }) {
  const deleteDocument = useDeleteDocument(agentId)
  const [toDelete, setToDelete] = useState(null)

  if (documents.isPending) {
    return (
      <div className="flex flex-col gap-2" role="status" aria-label="Loading documents">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    )
  }
  if (documents.isError) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-destructive">The documents couldn&apos;t load.</p>
        <Button variant="outline" size="sm" onClick={() => documents.refetch()}>
          Retry
        </Button>
      </div>
    )
  }
  if (documents.data.length === 0) {
    return <p className="text-sm text-muted-foreground">No documents yet. Add one above.</p>
  }

  function confirmDelete() {
    const doc = toDelete
    deleteDocument.mutate(doc.id, {
      onSuccess: () => toast.success('Document deleted'),
      onError: (err) => toast.error(err.message),
      onSettled: () => setToDelete(null),
    })
  }

  return (
    <>
      <ul className="divide-y rounded-xl border">
        {documents.data.map((doc) => (
          <li key={doc.id} className="flex items-start gap-3 p-3">
            <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="truncate text-sm font-medium">{doc.filename}</span>
                <StatusBadge status={doc.status} />
                <span className="text-xs text-muted-foreground">
                  {TYPE_LABELS[doc.source_type]}
                  {doc.status === 'ready' && ` · ${doc.chunk_count} ${doc.chunk_count === 1 ? 'section' : 'sections'}`}
                </span>
              </div>
              {doc.status === 'failed' && doc.error && <p className="mt-1 text-sm text-destructive">{doc.error}</p>}
            </div>
            <Button variant="ghost" size="icon-sm" aria-label={`Delete ${doc.filename}`} onClick={() => setToDelete(doc)}>
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>

      <AlertDialog open={Boolean(toDelete)} onOpenChange={(open) => !open && !deleteDocument.isPending && setToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {toDelete?.filename}?</AlertDialogTitle>
            <AlertDialogDescription>
              The agent will no longer be able to answer from it. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteDocument.isPending}>Keep document</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteDocument.isPending}
              onClick={(event) => {
                event.preventDefault() // keep the dialog open until the delete finishes
                confirmDelete()
              }}
            >
              Delete document
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export default function Knowledge({ agent, onNext, onBack }) {
  const update = useUpdateAgent()
  const documents = useDocuments(agent.id)
  const addDocument = useAddDocument(agent.id)
  const [pasteOpen, setPasteOpen] = useState(false)

  function save(changes) {
    update.mutate({ id: agent.id, ...changes }, { onError: (err) => toast.error(err.message) })
  }

  async function uploadFiles(accepted, rejected) {
    for (const { file, errors } of rejected) {
      const tooLarge = errors.some((error) => error.code === 'file-too-large')
      toast.error(tooLarge ? `${file.name} is larger than 10 MB.` : `${file.name} isn't a .pdf or .txt file.`)
    }
    for (const file of accepted) {
      const form = new FormData()
      form.append('file', file)
      // One at a time, awaited: every file gets its own success or error message.
      try {
        await addDocument.mutateAsync(form)
        toast.success(`${file.name} added`)
      } catch (err) {
        toast.error(`${file.name}: ${err.message}`)
      }
    }
  }

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: uploadFiles,
    accept: { 'application/pdf': ['.pdf'], 'text/plain': ['.txt'] },
    maxSize: MAX_FILE_BYTES,
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start gap-3">
        <Switch
          id="kb-enabled"
          checked={agent.kb_enabled}
          disabled={update.isPending}
          onCheckedChange={(checked) => save({ kb_enabled: checked })}
        />
        <div>
          <Label htmlFor="kb-enabled">Use a knowledge base</Label>
          <p className="mt-1 text-sm text-muted-foreground">
            Your agent searches the documents you add here and shows which one each answer came from.
          </p>
        </div>
      </div>

      {agent.kb_enabled && (
        <>
          <div className="flex flex-col gap-2">
            <span id="answer-mode-label" className="text-sm font-medium">
              What should it answer?
            </span>
            <div role="radiogroup" aria-labelledby="answer-mode-label" className="grid gap-3 sm:grid-cols-2">
              {ANSWER_MODES.map((mode) => {
                const selected = agent.kb_strict === mode.strict
                return (
                  <button
                    key={mode.title}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={update.isPending}
                    onClick={() => !selected && save({ kb_strict: mode.strict })}
                    className={cn(
                      'flex cursor-pointer flex-col gap-1 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                      selected ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted',
                    )}
                  >
                    <span className="text-sm font-medium">{mode.title}</span>
                    <span className="text-xs text-muted-foreground">{mode.description}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span id="search-mode-label" className="text-sm font-medium">
              How should it search?
            </span>
            <div role="radiogroup" aria-labelledby="search-mode-label" className="grid gap-3 sm:grid-cols-3">
              {SEARCH_MODES.map((mode) => {
                const selected = agent.search_mode === mode.key
                return (
                  <button
                    key={mode.key}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={update.isPending}
                    onClick={() => !selected && save({ search_mode: mode.key })}
                    className={cn(
                      'flex cursor-pointer flex-col gap-1 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                      selected ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'hover:bg-muted',
                    )}
                  >
                    <span className="text-sm font-medium">
                      {mode.title}
                      {mode.note && <span className="ml-2 text-xs font-normal text-primary">{mode.note}</span>}
                    </span>
                    <span className="text-xs text-muted-foreground">{mode.description}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Add documents</span>
            <div
              {...getRootProps()}
              className={cn(
                'flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed p-6 text-center outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
                isDragActive ? 'border-primary bg-primary/5' : 'hover:bg-muted',
              )}
            >
              <input {...getInputProps()} aria-label="Upload documents" />
              {addDocument.isPending ? (
                <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden="true" />
              ) : (
                <Upload className="size-5 text-muted-foreground" aria-hidden="true" />
              )}
              <p className="text-sm">
                {isDragActive ? 'Drop the files here' : 'Drag files here, or click to choose (.pdf or .txt, up to 10 MB)'}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" onClick={() => setPasteOpen(true)}>
                <Plus aria-hidden="true" /> Paste text
              </Button>
              <p className="text-sm text-muted-foreground">
                Text files and text-based PDFs. Scanned PDFs and images aren&apos;t supported yet.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Documents</span>
            <DocumentList agentId={agent.id} documents={documents} />
          </div>

          <PasteTextDialog open={pasteOpen} onOpenChange={setPasteOpen} addDocument={addDocument} />
        </>
      )}

      {/* Everything on this step saves as it changes, so Continue only moves on. */}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onNext()
        }}
      >
        <StepFooter onBack={onBack} saving={false} />
      </form>
    </div>
  )
}
