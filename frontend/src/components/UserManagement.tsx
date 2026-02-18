import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import {
  MdPeople,
  MdAdd,
  MdEdit,
  MdDelete,
  MdBlock,
  MdLockReset,
  MdEmail,
  MdClose
} from 'react-icons/md'
import './UserManagement.css'

interface User {
  id: string
  username: string
  email: string | null
  role: 'readonly' | 'write' | 'admin'
  blocked: boolean
  created_at: string
  microsoft_id: string | null
}

export default function UserManagement() {
  const queryClient = useQueryClient()
  const [isOpen, setIsOpen] = useState(false)
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
  const { data: allUsersForAdminCheck, isError: adminCheckError } = useQuery<User[]>({
    queryKey: ['users-for-admin-check'],
    queryFn: async () => {
      const response = await apiClient.get('/users')
      return response.data
    },
    retry: false, // Don't retry on 403
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  })

  // User is admin if we can successfully fetch the users list
  const isAdmin = !adminCheckError && allUsersForAdminCheck !== undefined

  // Get users list (for the modal)
  const { data: users, isLoading } = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: async () => {
      const response = await apiClient.get('/users')
      return response.data
    },
    enabled: isOpen && isAdmin, // Only fetch when modal is open and user is admin
  })

  const createUserMutation = useMutation({
    mutationFn: async (data: {
      username: string
      password: string
      email?: string
      role: 'readonly' | 'write' | 'admin'
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
      role: 'readonly' | 'write' | 'admin'
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
    mutationFn: async ({ userId, data }: { userId: string; data: Partial<User> }) => {
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
      role: formRole
    })
  }

  const handleInviteUser = (e: React.FormEvent) => {
    e.preventDefault()
    inviteUserMutation.mutate({
      email: inviteEmail,
      role: inviteRole,
      expires_hours: inviteExpiresHours
    })
  }

  const handleEditUser = (user: User) => {
    setEditingUser(user)
    setFormEmail(user.email || '')
    setFormRole(user.role)
    setShowCreateForm(true)
  }

  const handleUpdateUser = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingUser) return
    updateUserMutation.mutate({
      userId: editingUser.id,
      data: {
        email: formEmail || undefined,
        role: formRole,
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

  // Don't show if not admin
  if (!isAdmin) {
    return null
  }

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="user-management-btn"
        title="Nutzermanagement"
      >
        <MdPeople />
        <span>Nutzer</span>
      </button>

      {isOpen && (
        <div className="user-management-modal-overlay" onClick={() => setIsOpen(false)}>
          <div className="user-management-modal" onClick={(e) => e.stopPropagation()}>
            <div className="user-management-header">
              <h2>Nutzermanagement</h2>
              <button
                onClick={() => {
                  setIsOpen(false)
                  setShowCreateForm(false)
                  setShowInviteForm(false)
                  resetForm()
                }}
                className="close-btn"
              >
                <MdClose />
              </button>
            </div>

            <div className="user-management-actions">
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

            {showCreateForm && (
              <div className="user-form">
                <h3>{editingUser ? 'Benutzer bearbeiten' : 'Neuen Benutzer erstellen'}</h3>
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
              </div>
            )}

            {showInviteForm && (
              <div className="user-form">
                <h3>Einladung senden</h3>
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
              </div>
            )}

            <div className="users-list">
              <h3>Benutzer</h3>
              {isLoading ? (
                <div>Laden...</div>
              ) : users && users.length > 0 ? (
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
                          <span className={`badge badge-${user.role === 'admin' ? 'danger' : user.role === 'write' ? 'warning' : 'secondary'}`}>
                            {user.role}
                          </span>
                        </td>
                        <td>
                          {user.blocked ? (
                            <span className="badge badge-danger">Blockiert</span>
                          ) : (
                            <span className="badge badge-success">Aktiv</span>
                          )}
                        </td>
                        <td>{new Date(user.created_at).toLocaleDateString(getFormatLocale())}</td>
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
              ) : (
                <div className="empty-state">Keine Benutzer gefunden</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
