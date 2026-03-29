import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [isOpen, setIsOpen] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [resetPasswordUserId, setResetPasswordUserId] = useState<string | null>(null)
  const [resetPasswordValue, setResetPasswordValue] = useState('')

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
      showSuccess(t('users.toastUserCreated'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
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
      showSuccess(t('users.toastInviteCreatedWithLink', { link: fullLink }))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
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
      showSuccess(t('users.toastUserUpdated'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
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
      showSuccess(t('users.toastPasswordReset'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const blockUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.post(`/users/${userId}/block`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess(t('users.toastUserBlocked'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const unblockUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.post(`/users/${userId}/unblock`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess(t('users.toastUserUnblocked'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.delete(`/users/${userId}`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      showSuccess(t('users.toastUserDeleted'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
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

  const handleResetPassword = (userId: string) => {
    setResetPasswordUserId(userId)
    setResetPasswordValue('')
  }

  const handleResetPasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!resetPasswordUserId) return
    if (resetPasswordValue.length < 6) {
      showError(t('users.passwordMinLength'))
      return
    }
    resetPasswordMutation.mutate({ userId: resetPasswordUserId, newPassword: resetPasswordValue })
    setResetPasswordUserId(null)
    setResetPasswordValue('')
  }

  const handleBlockUser = async (userId: string) => {
    const confirmed = await showConfirm(t('users.confirmBlock'))
    if (confirmed) {
      blockUserMutation.mutate(userId)
    }
  }

  const handleUnblockUser = async (userId: string) => {
    const confirmed = await showConfirm(t('users.confirmUnblock'))
    if (confirmed) {
      unblockUserMutation.mutate(userId)
    }
  }

  const handleDeleteUser = async (userId: string) => {
    const confirmed = await showConfirm(t('users.confirmDelete'))
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
        title={t('users.managementTitle')}
      >
        <MdPeople />
        <span>{t('users.shortLabel')}</span>
      </button>

      {resetPasswordUserId && (
        <div
          className="user-management-modal-overlay"
          onClick={() => setResetPasswordUserId(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="reset-password-title"
        >
          <div
            className="user-management-modal"
            style={{ maxWidth: 400 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="user-management-header">
              <h2 id="reset-password-title">{t('users.resetPasswordTitle')}</h2>
              <button
                onClick={() => setResetPasswordUserId(null)}
                className="close-btn"
                aria-label={t('users.closeAria')}
              >
                <MdClose />
              </button>
            </div>
            <form onSubmit={handleResetPasswordSubmit} className="user-form">
              <div className="form-group">
                <label htmlFor="reset-password-input">{t('users.newPassword')}:</label>
                <input
                  id="reset-password-input"
                  type="password"
                  value={resetPasswordValue}
                  onChange={(e) => setResetPasswordValue(e.target.value)}
                  minLength={6}
                  required
                  autoFocus
                  autoComplete="new-password"
                />
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-success">
                  {t('users.setPassword')}
                </button>
                <button
                  type="button"
                  onClick={() => setResetPasswordUserId(null)}
                  className="btn btn-secondary"
                >
                  {t('common.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {isOpen && (
        <div className="user-management-modal-overlay" onClick={() => setIsOpen(false)}>
          <div className="user-management-modal" onClick={(e) => e.stopPropagation()}>
            <div className="user-management-header">
              <h2>{t('users.managementTitle')}</h2>
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
                {t('users.createUser')}
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
                {t('users.sendInvite')}
              </button>
            </div>

            {showCreateForm && (
              <div className="user-form">
                <h3>{editingUser ? t('users.editUser') : t('users.newUser')}</h3>
                <form onSubmit={editingUser ? handleUpdateUser : handleCreateUser}>
                  {!editingUser && (
                    <>
                      <div className="form-group">
                        <label>{t('users.username')}:</label>
                        <input
                          type="text"
                          value={formUsername}
                          onChange={(e) => setFormUsername(e.target.value)}
                          required
                        />
                      </div>
                      <div className="form-group">
                        <label>{t('users.password')}:</label>
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
                    <label>{t('users.emailOptional')}:</label>
                    <input
                      type="email"
                      value={formEmail}
                      onChange={(e) => setFormEmail(e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label>{t('users.roleLabel')}</label>
                    <select
                      value={formRole}
                      onChange={(e) => setFormRole(e.target.value as 'readonly' | 'write' | 'admin')}
                      required
                    >
                      <option value="readonly">{t('users.roleOptionReadonly')}</option>
                      <option value="write">{t('users.roleOptionWrite')}</option>
                      <option value="admin">{t('users.roleOptionAdmin')}</option>
                    </select>
                  </div>
                  <div className="form-actions">
                    <button type="submit" className="btn btn-success">
                      {editingUser ? t('users.update') : t('users.createUser')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShowCreateForm(false)
                        resetForm()
                      }}
                      className="btn btn-secondary"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </form>
              </div>
            )}

            {showInviteForm && (
              <div className="user-form">
                <h3>{t('users.sendInvite')}</h3>
                <form onSubmit={handleInviteUser}>
                  <div className="form-group">
                    <label>{t('users.email')}:</label>
                    <input
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>{t('users.roleLabel')}</label>
                    <select
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value as 'readonly' | 'write' | 'admin')}
                      required
                    >
                      <option value="readonly">{t('users.roleOptionReadonly')}</option>
                      <option value="write">{t('users.roleOptionWrite')}</option>
                      <option value="admin">{t('users.roleOptionAdmin')}</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>{t('users.validForHours')}</label>
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
                      {t('users.createInvite')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShowInviteForm(false)
                        resetInviteForm()
                      }}
                      className="btn btn-secondary"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </form>
              </div>
            )}

            <div className="users-list">
              <h3>{t('users.usersListHeading')}</h3>
              {isLoading ? (
                <div>{t('users.loading')}</div>
              ) : users && users.length > 0 ? (
                <table className="users-table">
                  <thead>
                    <tr>
                      <th>{t('users.username')}</th>
                      <th>{t('users.email')}</th>
                      <th>{t('users.role')}</th>
                      <th>{t('users.status')}</th>
                      <th>{t('users.createdAt')}</th>
                      <th>{t('users.actions')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((user) => (
                      <tr key={user.id} className={user.blocked ? 'blocked' : ''}>
                        <td>{user.username}</td>
                        <td>{user.email || '-'}</td>
                        <td>
                          <span className={`badge badge-${user.role === 'admin' ? 'danger' : user.role === 'write' ? 'warning' : 'secondary'}`}>
                            {user.role === 'admin' ? t('users.roleDisplayAdmin') : user.role === 'write' ? t('users.roleDisplayWrite') : t('users.roleDisplayReadonly')}
                          </span>
                        </td>
                        <td>
                          {user.blocked ? (
                            <span className="badge badge-danger">{t('users.badgeBlocked')}</span>
                          ) : (
                            <span className="badge badge-success">{t('users.badgeActive')}</span>
                          )}
                        </td>
                        <td>{new Date(user.created_at).toLocaleDateString(getFormatLocale())}</td>
                        <td>
                          <div className="user-actions">
                            <button
                              onClick={() => handleEditUser(user)}
                              className="btn-icon"
                              title={t('users.edit')}
                            >
                              <MdEdit />
                            </button>
                            <button
                              onClick={() => handleResetPassword(user.id)}
                              className="btn-icon"
                              title={t('users.resetPasswordTooltip')}
                            >
                              <MdLockReset />
                            </button>
                            {user.blocked ? (
                              <button
                                onClick={() => handleUnblockUser(user.id)}
                                className="btn-icon"
                                title={t('users.unblock')}
                              >
                                <MdBlock />
                              </button>
                            ) : (
                              <button
                                onClick={() => handleBlockUser(user.id)}
                                className="btn-icon"
                                title={t('users.block')}
                              >
                                <MdBlock />
                              </button>
                            )}
                            <button
                              onClick={() => handleDeleteUser(user.id)}
                              className="btn-icon btn-danger"
                              title={t('common.delete')}
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
                <div className="empty-state">{t('users.noUsersFound')}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
