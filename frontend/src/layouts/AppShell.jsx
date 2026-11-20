import { BarChart3, Bot, ChevronsUpDown, KeyRound, LogOut, Menu, MessageSquare, Workflow } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { ApiKeysDialog } from '@/components/ApiKeysDialog'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/app/agents', label: 'Create your agent', icon: Bot },
  { to: '/app/chat', label: 'Chat with your agent', icon: MessageSquare },
  { to: '/app/automations', label: 'Automations', icon: Workflow },
  { to: '/app/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/app/api', label: 'API', icon: KeyRound },
]

function Brand() {
  return (
    <div className="flex items-center gap-2 px-2 font-semibold">
      <Bot className="size-5 text-primary" aria-hidden="true" />
      Custom Agent Platform
    </div>
  )
}

function NavItems({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-1" aria-label="Main">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/50',
              isActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )
          }
        >
          <item.icon className="size-4 shrink-0" aria-hidden="true" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

function UserMenu({ onOpenApiKeys }) {
  const { user, session, signOut } = useAuth()
  const name = user?.name || session?.user?.email || 'Account'
  const initial = name.trim().charAt(0).toUpperCase()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-auto w-full justify-start gap-2.5 px-2 py-2">
          <Avatar className="size-7">
            <AvatarImage src={user?.avatar_url ?? undefined} alt="" />
            <AvatarFallback>{initial}</AvatarFallback>
          </Avatar>
          <span className="min-w-0 flex-1 truncate text-left text-sm">{name}</span>
          <ChevronsUpDown className="size-4 text-muted-foreground" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-56">
        <DropdownMenuItem onSelect={onOpenApiKeys}>
          <KeyRound aria-hidden="true" /> API keys
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={signOut}>
          <LogOut aria-hidden="true" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [keysOpen, setKeysOpen] = useState(false)
  const openApiKeys = () => setKeysOpen(true)

  return (
    <div className="flex h-svh">
      <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r bg-muted/30 p-3 md:flex">
        <div className="pt-2">
          <Brand />
        </div>
        <div className="flex-1">
          <NavItems />
        </div>
        <div className="border-t pt-3">
          <UserMenu onOpenApiKeys={openApiKeys} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b p-2 md:hidden">
          <Button variant="ghost" size="icon" onClick={() => setDrawerOpen(true)} aria-label="Open menu">
            <Menu aria-hidden="true" />
          </Button>
          <Brand />
        </header>
        {/* relative: the hidden inputs behind switches and checkboxes are absolutely positioned;
            without it they escape this scroller and make the whole page scroll into blank space. */}
        <main className="relative min-h-0 flex-1 overflow-auto">
          <Outlet context={{ openApiKeys }} />
        </main>
      </div>

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="flex w-64 flex-col gap-6 p-3">
          <SheetHeader className="p-0 pt-2">
            <SheetTitle>
              <Brand />
            </SheetTitle>
            <SheetDescription className="sr-only">Main menu</SheetDescription>
          </SheetHeader>
          <div className="flex-1">
            <NavItems onNavigate={() => setDrawerOpen(false)} />
          </div>
          <div className="border-t pt-3">
            <UserMenu
              onOpenApiKeys={() => {
                setDrawerOpen(false)
                openApiKeys()
              }}
            />
          </div>
        </SheetContent>
      </Sheet>

      <ApiKeysDialog open={keysOpen} onOpenChange={setKeysOpen} />
    </div>
  )
}
