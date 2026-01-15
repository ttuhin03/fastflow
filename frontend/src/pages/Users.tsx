import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import {
  MdAdd,
  MdEdit,
  MdDelete,
  MdBlock,
  MdLockReset,
  MdEmail,
  MdClose
} from 'react-icons/md'
import './Users.css'

interface User {
  id: string
  username: string
  email: string | null
  role: 'readonly' | 'write' | 'admin' | 'READONLY' | 'WRITE' | 'ADMIN'
  blocked: boolean
  created_at: string
  microsoft_id: string | null
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
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  // Form states
  const [formUsername, setFormUsername] = useState('')
  const [formPassword, setFormPassword] = useState('')
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
    retry: false, // Don't retry on 403
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
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

  const createUserMutation = useMutation({
    mutationFn: async (data: {
      username: string
      password: string
      email?: string
      role: 'READONLY' | 'WRITE' | 'ADMIN'
    }) => {
      const response = await apiClient.post('/users', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setShowCreateForm(false)
      resetForm()
      showSuccess('Benutzer erfolgreich erstellt')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const inviteUserMutation = useMutation({
    mutationFn: async (data: {
      email: string
      role: 'READONLY' | 'WRITE' | 'ADMIN'
      expires_hours: number
    }) => {
      const response = await apiClient.post('/users/invite', data)
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setShowInviteForm(false)
      resetInviteForm()
      // Show invite link
      const fullLink = `${window.location.origin}/invite/${data.token}`
      navigator.clipboard.writeText(fullLink)
      showSuccess(`Einladungslink erstellt und in Zwischenablage kopiert: ${fullLink}`)
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
      setShowCreateForm(false)
      showSuccess('Benutzer erfolgreich aktualisiert')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const resetPasswordMutation = useMutation({
    mutationFn: async ({ userId, newPassword }: { userId: string; newPassword: string }) => {
      const response = await apiClient.post(`/users/${userId}/reset-password`, {
        new_password: newPassword
      })
      return response.data
    },
    onSuccess: () => {
      showSuccess('Passwort erfolgreich zurückgesetzt')
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

  const resetForm = () => {
    setFormUsername('')
    setFormPassword('')
    setFormEmail('')
    setFormRole('readonly')
    setEditingUser(null)
  }

  const resetInviteForm = () => {
    setInviteEmail('')
    setInviteRole('readonly')
    setInviteExpiresHours(168)
  }

  const handleCreateUser = (e: React.FormEvent) => {
    e.preventDefault()
    createUserMutation.mutate({
      username: formUsername,
      password: formPassword,
      email: formEmail || undefined,
      role: roleToUppercase(formRole)
    })
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
    setShowCreateForm(true)
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

  const handleResetPassword = async (userId: string) => {
    // Für Passwort-Eingabe verwenden wir einen einfachen Prompt (kann später durch ein Modal ersetzt werden)
    const newPassword = window.prompt('Neues Passwort eingeben:')
    if (newPassword && newPassword.length >= 6) {
      resetPasswordMutation.mutate({ userId, newPassword })
    } else if (newPassword) {
      showError('Passwort muss mindestens 6 Zeichen lang sein')
    }
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
              setShowCreateForm(true)
              setShowInviteForm(false)
              resetForm()
            }}
            className="btn btn-primary"
          >
            <MdAdd />
            Nutzer erstellen
          </button>
          <button
            onClick={() => {
              setShowInviteForm(true)
              setShowCreateForm(false)
              resetInviteForm()
            }}
            className="btn btn-primary"
          >
            <MdEmail />
            Einladung senden
          </button>
        </div>
      </div>

      {(showCreateForm || showInviteForm) && (
        <div className="users-form-card">
          <div className="users-form-header">
            <h3>
              {showInviteForm 
                ? 'Einladung senden' 
                : editingUser 
                  ? 'Benutzer bearbeiten' 
                  : 'Neuen Benutzer erstellen'}
            </h3>
            <button
              onClick={() => {
                setShowCreateForm(false)
                setShowInviteForm(false)
                resetForm()
                resetInviteForm()
              }}
              className="close-btn"
            >
              <MdClose />
            </button>
          </div>

          {showCreateForm && (
            <form onSubmit={editingUser ? handleUpdateUser : handleCreateUser}>
              {!editingUser && (
                <>
                  <div className="form-group">
                    <label>Benutzername:</label>
                    <input
                      type="text"
                      value={formUsername}
                      onChange={(e) => setFormUsername(e.target.value)}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>Passwort:</label>
                    <input
                      type="password"
                      value={formPassword}
                      onChange={(e) => setFormPassword(e.target.value)}
                      required={!editingUser}
                      minLength={6}
                    />
                  </div>
                </>
              )}
              <div className="form-group">
                <label>E-Mail (optional):</label>
                <input
                  type="email"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Rolle:</label>
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
                <button type="submit" className="btn btn-success">
                  {editingUser ? 'Aktualisieren' : 'Erstellen'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateForm(false)
                    resetForm()
                  }}
                  className="btn btn-secondary"
                >
                  Abbrechen
                </button>
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
                <label>Rolle:</label>
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
                <label>Gültig für (Stunden):</label>
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
        <h3>Benutzer</h3>
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
                    <td>{user.username}</td>
                    <td>{user.email || '-'}</td>
                    <td>
                      <span className={`badge badge-${normalizeRole(user.role) === 'admin' ? 'admin' : normalizeRole(user.role) === 'write' ? 'write' : 'readonly'}`}>
                        {normalizeRole(user.role)}
                      </span>
                    </td>
                    <td>
                      {user.blocked ? (
                        <span className="badge badge-error">Blockiert</span>
                      ) : (
                        <span className="badge badge-success">Aktiv</span>
                      )}
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
                        <button
                          onClick={() => handleResetPassword(user.id)}
                          className="btn-icon"
                          title="Passwort zurücksetzen"
                        >
                          <MdLockReset />
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
    </div>
  )
}
