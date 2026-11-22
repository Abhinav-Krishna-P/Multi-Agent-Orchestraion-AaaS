import { ApiKeyField } from '@/components/ApiKeyField'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmKeys, useModelCatalog } from '@/lib/queries'

export function ApiKeysDialog({ open, onOpenChange }) {
  const catalog = useModelCatalog()
  const llmKeys = useLlmKeys()
  const loading = catalog.isPending || llmKeys.isPending
  const failed = catalog.isError || llmKeys.isError

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>API keys</DialogTitle>
          <DialogDescription>
            Your key is used only for your agents&apos; chat replies. It&apos;s stored encrypted.
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex flex-col gap-4">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : failed ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-sm text-destructive">Your API keys couldn&apos;t load.</p>
            <Button
              variant="outline"
              onClick={() => {
                catalog.refetch()
                llmKeys.refetch()
              }}
            >
              Retry
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            {catalog.data.providers.map((provider) => (
              <ApiKeyField
                key={provider.key}
                provider={provider.key}
                providerName={provider.name}
                savedKey={llmKeys.data.find((saved) => saved.provider === provider.key)}
              />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
