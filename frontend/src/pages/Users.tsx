import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { MdEdit, MdDelete, MdBlock, MdEmail, MdClose, MdOpenInNew } from 'react-icons/md'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import './Users.css'

interface User {
  id: string
  username: string
  email: string | null
  role: 'readonly' | 'write' | 'admin' | 'READONLY' | 'WRITE' | 'ADMIN'
  blocked: boolean
  created_at: string
  microsoft_id: string | null
  github_id?: string | null
}

interface InvitationRow {
  id: string
  recipient_email: string
  is_used: boolean
  expires_at: string
  created_at: string
  role: string
}

// Helper function to convert role to uppercase for API
const roleToUppercase = (role: 'readonly' | 'write' | 'admin'): 'READONLY' | 'WRITE' | 'ADMIN' => {
  return role.toUpperCase() as 'READONLY' | 'WRITE' | 'ADMIN'
}

// Helper function to normalize role from API (might be uppercase or lowercase)
const normalizeRole = (role: string): 'readonly' | 'write' | 'admin' => {
  return role.toLowerCase() as 'readonly' | 'write' | 'admin'
}

export default function Users() {
  const queryClient = useQueryClient()
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [formEmail, setFormEmail] = useState('')
  const [formRole, setFormRole] = useState<'readonly' | 'write' | 'admin'>('readonly')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'readonly' | 'write' | 'admin'>('readonly')
  const [inviteExpiresHours, setInviteExpiresHours] = useState(168)

  // Check if current user is admin by trying to fetch users list
  // If successful, user is admin. If 403, user is not admin.
  const { data: users, isLoading, isError, error } = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: async () => {
      const response = await apiClient.get('/users')
      return response.data
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const { data: invites = [] } = useQuery<InvitationRow[]>({
    queryKey: ['invites'],
    queryFn: async () => {
      const response = await apiClient.get('/users/invites')
      return response.data
    },
    retry: false,
    staleTime: 2 * 60 * 1000,
  })

  // Show message if not admin (403 Forbidden) or if error detail contains "Admin"
  const errorResponse = (error as any)?.response
  const is403Error = errorResponse?.status === 403
  const isAdminError = errorResponse?.data?.detail?.includes?.('Admin') || 
                       errorResponse?.data?.detail === 'Admin-Rechte erforderlich'
  
  if (isError && (is403Error || isAdminError)) {
    return (
      <div className="users-page">
        <div className="users-list-card">
          <div className="empty-state">
            <h3>Zugriff verweigert</h3>
            <p>Sie haben keine Berechtigung, auf die Nutzerverwaltung zuzugreifen. Diese Funktion ist nur für Administratoren verfügbar.</p>
            {errorResponse?.data?.detail && (
              <p style={{ marginTop: '0.5rem', fontSize: '0.875rem', opacity: 0.8 }}>
                {errorResponse.data.detail}
              </p>
            )}
          </div>
        </div>
      </div>
    )
  }

  const inviteUserMutation = useMutation({
    mutationFn: async (data: {
      email: string
      role: 'READONLY' | 'WRITE' | 'ADMIN'
      expires_hours: number
    }) => {
      const response = await apiClient.post('/users/invite', data)
      return response.data
    },
    onSuccess: (data: { link: string; expires_at: string }) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['invites'] })
      setShowInviteForm(false)
      resetInviteForm()
      navigator.clipboard.writeText(data.link)
      showSuccess('Einladungslink erstellt und in Zwischenablage kopiert')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateUserMutation = useMutation({
    mutationFn: async ({ userId, data }: { 
      userId: string
      data: {
        email?: string
        role?: 'READONLY' | 'WRITE' | 'ADMIN'
        blocked?: boolean
      }
    }) => {
      const response = await apiClient.put(`/users/${userId}`, data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setEditingUser(null)
      resetForm()
      showSuccess('Benutzer erfolgreich aktualisiert')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const blockUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.post(`/users/${userId}/block`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess('Benutzer erfolgreich blockiert')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const unblockUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.post(`/users/${userId}/unblock`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess('Benutzer erfolgreich entblockiert')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.delete(`/users/${userId}`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess('Benutzer erfolgreich gelöscht')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteInviteMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/users/invites/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invites'] })
      showSuccess('Einladung widerrufen')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const resetForm = () => {
    setFormEmail('')
    setFormRole('readonly')
    setEditingUser(null)
  }

  const resetInviteForm = () => {
    setInviteEmail('')
    setInviteRole('readonly')
    setInviteExpiresHours(168)
  }

  const handleInviteUser = (e: React.FormEvent) => {
    e.preventDefault()
    inviteUserMutation.mutate({
      email: inviteEmail,
      role: roleToUppercase(inviteRole),
      expires_hours: inviteExpiresHours
    })
  }

  const handleEditUser = (user: User) => {
    setEditingUser(user)
    setFormEmail(user.email || '')
    setFormRole(normalizeRole(user.role))
    setShowInviteForm(false)
  }

  const handleUpdateUser = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingUser) return
    updateUserMutation.mutate({
      userId: editingUser.id,
      data: {
        email: formEmail || undefined,
        role: roleToUppercase(formRole),
        blocked: editingUser.blocked
      }
    })
  }

  const handleBlockUser = async (userId: string) => {
    const confirmed = await showConfirm('Möchten Sie diesen Benutzer wirklich blockieren?')
    if (confirmed) {
      blockUserMutation.mutate(userId)
    }
  }

  const handleUnblockUser = async (userId: string) => {
    const confirmed = await showConfirm('Möchten Sie diesen Benutzer wirklich entblockieren?')
    if (confirmed) {
      unblockUserMutation.mutate(userId)
    }
  }

  const handleDeleteUser = async (userId: string) => {
    const confirmed = await showConfirm('Möchten Sie diesen Benutzer wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.')
    if (confirmed) {
      deleteUserMutation.mutate(userId)
    }
  }

  return (
    <div className="users-page">
      <div className="users-header">
        <div className="users-actions">
          <button
            onClick={() => {
              setShowInviteForm(true)
              resetInviteForm()
            }}
            className="btn btn-primary"
          >
            <MdEmail />
            Einladung senden
          </button>
        </div>
      </div>

      {(editingUser || showInviteForm) && (
        <div className="users-form-card">
          <div className="users-form-header">
            <h3>{showInviteForm ? 'Einladung senden' : 'Benutzer bearbeiten'}</h3>
            <button
              onClick={() => {
                setShowInviteForm(false)
                resetForm()
                resetInviteForm()
              }}
              className="close-btn"
            >
              <MdClose />
            </button>
          </div>

          {editingUser && (
            <form onSubmit={handleUpdateUser}>
              <div className="form-group">
                <label>E-Mail (optional):</label>
                <input
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>
                  Rolle:
                  <InfoIcon content="Readonly: Nur Leserechte. Write: Schreibrechte. Admin: Vollzugriff." />
                </label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value as 'readonly' | 'write' | 'admin')}
                  required
                >
                  <option value="readonly">Readonly</option>
                  <option value="write">Write</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-success">Aktualisieren</button>
                <button type="button" onClick={() => { setEditingUser(null); resetForm() }} className="btn btn-secondary">Abbrechen</button>
              </div>
            </form>
          )}

          {showInviteForm && (
            <form onSubmit={handleInviteUser}>
              <div className="form-group">
                <label>E-Mail:</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label>
                  Rolle:
                  <InfoIcon content="Readonly: Nur Leserechte (Pipelines anschauen, Runs ansehen). Write: Schreibrechte (Pipelines starten, Secrets verwalten). Admin: Vollzugriff (User-Verwaltung, Einstellungen)" />
                </label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'readonly' | 'write' | 'admin')}
                  required
                >
                  <option value="readonly">Readonly</option>
                  <option value="write">Write</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div className="form-group">
                <label>
                  Gültig für (Stunden):
                  <InfoIcon content="Gültigkeitsdauer des Einladungslinks (Standard: 168h = 7 Tage)" />
                </label>
                <input
                  type="number"
                  value={inviteExpiresHours}
                  onChange={(e) => setInviteExpiresHours(parseInt(e.target.value))}
                  min={1}
                  max={720}
                  required
                />
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-success">
                  Einladung erstellen
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowInviteForm(false)
                    resetInviteForm()
                  }}
                  className="btn btn-secondary"
                >
                  Abbrechen
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      <div className="users-list-card">
        <h3 className="users-section-title">
          Benutzer
          <InfoIcon content="Alle Benutzer melden sich über GitHub an. Der erste Admin wird über INITIAL_ADMIN_EMAIL festgelegt, weitere über Einladungen." />
        </h3>
        {isLoading ? (
          <div className="loading-state">Laden...</div>
        ) : users && users.length > 0 ? (
          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Benutzername</th>
                  <th>E-Mail</th>
                  <th>Rolle</th>
                  <th>Status</th>
                  <th>Erstellt</th>
                  <th>Aktionen</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} className={user.blocked ? 'blocked' : ''}>
                    <td>
                      {user.github_id ? (
                        <a
                          href={`https://github.com/${user.username}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="github-user-link"
                          title={`GitHub: @${user.username}`}
                        >
                          {user.username}
                          <MdOpenInNew className="icon-external" />
                        </a>
                      ) : (
                        user.username
                      )}
                    </td>
                    <td>{user.email || '-'}</td>
                    <td>
                      <Tooltip content={
                        normalizeRole(user.role) === 'admin' ? 'Admin: Vollzugriff (User-Verwaltung, Einstellungen)' :
                        normalizeRole(user.role) === 'write' ? 'Write: Schreibrechte (Pipelines starten, Secrets verwalten)' :
                        'Readonly: Nur Leserechte (Pipelines anschauen, Runs ansehen)'
                      }>
                        <span className={`badge badge-${normalizeRole(user.role) === 'admin' ? 'admin' : normalizeRole(user.role) === 'write' ? 'write' : 'readonly'}`}>
                          {normalizeRole(user.role)}
                        </span>
                      </Tooltip>
                    </td>
                    <td>
                      <Tooltip content={user.blocked ? 'Blockierte User können sich nicht anmelden' : 'User ist aktiv und kann sich anmelden'}>
                        {user.blocked ? (
                          <span className="badge badge-error">Blockiert</span>
                        ) : (
                          <span className="badge badge-success">Aktiv</span>
                        )}
                      </Tooltip>
                    </td>
                    <td>{new Date(user.created_at).toLocaleDateString('de-DE')}</td>
                    <td>
                      <div className="user-actions">
                        <button
                          onClick={() => handleEditUser(user)}
                          className="btn-icon"
                          title="Bearbeiten"
                        >
                          <MdEdit />
                        </button>
                        {user.blocked ? (
                          <button
                            onClick={() => handleUnblockUser(user.id)}
                            className="btn-icon"
                            title="Entblockieren"
                          >
                            <MdBlock />
                          </button>
                        ) : (
                          <button
                            onClick={() => handleBlockUser(user.id)}
                            className="btn-icon"
                            title="Blockieren"
                          >
                            <MdBlock />
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteUser(user.id)}
                          className="btn-icon btn-danger"
                          title="Löschen"
                        >
                          <MdDelete />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">Keine Benutzer gefunden</div>
        )}
      </div>

      <div className="users-list-card" style={{ marginTop: '1.5rem' }}>
        <h3>Einladungen</h3>
        {invites.length === 0 ? (
          <div className="empty-state">Keine Einladungen</div>
        ) : (
          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>E-Mail</th>
                  <th>Rolle</th>
                  <th>Erstellt</th>
                  <th>Läuft ab</th>
                  <th>Status</th>
                  <th>Aktionen</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.id}>
                    <td>{i.recipient_email}</td>
                    <td><span className={`badge badge-${normalizeRole(i.role)}`}>{normalizeRole(i.role)}</span></td>
                    <td>{new Date(i.created_at).toLocaleString('de-DE')}</td>
                    <td>{new Date(i.expires_at).toLocaleString('de-DE')}</td>
                    <td>{i.is_used ? <span className="badge badge-success">Eingelöst</span> : <span className="badge">Offen</span>}</td>
                    <td>
                      {!i.is_used && new Date(i.expires_at) > new Date() && (
                        <button
                          onClick={() => deleteInviteMutation.mutate(i.id)}
                          className="btn-icon btn-danger"
                          title="Widerrufen"
                        >
                          <MdDelete />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
