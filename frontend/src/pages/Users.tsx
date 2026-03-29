import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getFormatLocale } from '../utils/locale'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { MdEdit, MdDelete, MdBlock, MdEmail, MdClose, MdOpenInNew, MdCheck, MdCancel } from 'react-icons/md'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import { useAuth } from '../contexts/AuthContext'
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
  github_login?: string | null
  google_id?: string | null
  status?: string
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

function linkedProviderKeys(user: User): Array<'github' | 'google'> {
  const a: Array<'github' | 'google'> = []
  if (user.github_id) a.push('github')
  if (user.google_id) a.push('google')
  return a
}

function providerCellKey(user: User): 'users.providerGitHub' | 'users.providerGoogle' | 'users.providerNone' {
  if (user.github_id) return 'users.providerGitHub'
  if (user.google_id) return 'users.providerGoogle'
  return 'users.providerNone'
}

interface UsersProps {
  /** Gesperrt aus den Einstellungen (Schloss): keine Admin-Aktionen bis Entsperren */
  editLocked?: boolean
}

export default function Users({ editLocked = false }: UsersProps) {
  const { t } = useTranslation()
  const { isAdmin } = useAuth()
  const adminActionsDisabled = editLocked
  const queryClient = useQueryClient()
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [formRole, setFormRole] = useState<'readonly' | 'write' | 'admin'>('readonly')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'readonly' | 'write' | 'admin'>('readonly')
  const [inviteExpiresHours, setInviteExpiresHours] = useState(168)
  const [approveModalUser, setApproveModalUser] = useState<User | null>(null)
  const [approveRole, setApproveRole] = useState<'readonly' | 'write' | 'admin'>('readonly')

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
            <h3>{t('users.accessDeniedTitle')}</h3>
            <p>{t('users.accessDeniedBody')}</p>
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
      const until = new Date(data.expires_at).toLocaleString(getFormatLocale())
      showSuccess(t('users.toastInviteCopied', { until }))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const updateUserMutation = useMutation({
    mutationFn: async ({ userId, data }: { 
      userId: string
      data: { role: 'READONLY' | 'WRITE' | 'ADMIN' }
    }) => {
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

  const deleteInviteMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/users/invites/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invites'] })
      showSuccess(t('users.toastInviteRevoked'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const approveUserMutation = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: 'READONLY' | 'WRITE' | 'ADMIN' }) => {
      const response = await apiClient.post(`/users/${userId}/approve`, { role })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['invites'] })
      setApproveModalUser(null)
      setApproveRole('readonly')
      showSuccess(t('users.toastJoinApproved'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const rejectUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await apiClient.post(`/users/${userId}/reject`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['invites'] })
      showSuccess(t('users.toastJoinRejected'))
    },
    onError: (error: any) => {
      showError(t('users.errorWithDetail', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const resetForm = () => {
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
    setFormRole(normalizeRole(user.role))
    setShowInviteForm(false)
  }

  const handleUpdateUser = (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingUser) return
    updateUserMutation.mutate({
      userId: editingUser.id,
      data: { role: roleToUppercase(formRole) }
    })
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

  const handleOpenApproveModal = (user: User) => {
    setApproveModalUser(user)
    setApproveRole('readonly')
  }

  const handleApproveUser = (e: React.FormEvent) => {
    e.preventDefault()
    if (!approveModalUser) return
    approveUserMutation.mutate({ userId: approveModalUser.id, role: roleToUppercase(approveRole) })
  }

  const handleRejectUser = async (userId: string) => {
    const confirmed = await showConfirm(t('users.confirmRejectJoin'))
    if (confirmed) {
      rejectUserMutation.mutate(userId)
    }
  }

  const activeUsers = (users || []).filter((u) => (u.status || 'active') === 'active')
  const pendingUsers = (users || []).filter((u) => (u.status || 'active') === 'pending')

  return (
    <div className="users-page">
      {isAdmin && (
        <div className="users-header">
          <div className="users-actions">
            <button
              onClick={() => {
                setShowInviteForm(true)
                resetInviteForm()
              }}
              className="btn btn-primary"
              disabled={adminActionsDisabled}
            >
              <MdEmail />
              {t('users.sendInvite')}
            </button>
          </div>
        </div>
      )}

      {isAdmin && approveModalUser && (
        <div className="users-form-card" style={{ marginBottom: '1rem' }}>
          <div className="users-form-header">
            <h3>{t('users.approveJoinTitle')}</h3>
            <button onClick={() => setApproveModalUser(null)} className="close-btn"><MdClose /></button>
          </div>
          <p style={{ marginBottom: '1rem', color: 'var(--color-text-secondary)' }}>
            <strong>{approveModalUser.username}</strong> ({approveModalUser.email || t('users.noEmail')}) – {t('users.assignRole')}
          </p>
          <form onSubmit={handleApproveUser}>
            <div className="form-group">
              <label>{t('users.roleLabel')}</label>
              <select
                value={approveRole}
                onChange={(e) => setApproveRole(e.target.value as 'readonly' | 'write' | 'admin')}
                required
                disabled={adminActionsDisabled}
              >
                <option value="readonly">{t('users.roleOptionReadonly')}</option>
                <option value="write">{t('users.roleOptionWrite')}</option>
                <option value="admin">{t('users.roleOptionAdmin')}</option>
              </select>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn btn-success" disabled={adminActionsDisabled}><MdCheck /> {t('users.approve')}</button>
              <button type="button" onClick={() => setApproveModalUser(null)} className="btn btn-secondary">{t('common.cancel')}</button>
            </div>
          </form>
        </div>
      )}

      {isAdmin && (editingUser || showInviteForm) && (
        <div className="users-form-card">
          <div className="users-form-header">
            <h3>{showInviteForm ? t('users.sendInvite') : t('users.editUser')}</h3>
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
                <label>
                  {t('users.roleLabel')}
                  <InfoIcon content={t('users.roleEditHint')} />
                </label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value as 'readonly' | 'write' | 'admin')}
                  required
                  disabled={adminActionsDisabled}
                >
                  <option value="readonly">{t('users.roleOptionReadonly')}</option>
                  <option value="write">{t('users.roleOptionWrite')}</option>
                  <option value="admin">{t('users.roleOptionAdmin')}</option>
                </select>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-success" disabled={adminActionsDisabled}>{t('users.update')}</button>
                <button type="button" onClick={() => { setEditingUser(null); resetForm() }} className="btn btn-secondary">{t('common.cancel')}</button>
              </div>
            </form>
          )}

          {showInviteForm && (
            <form onSubmit={handleInviteUser}>
              <div className="form-group">
                <label>{t('users.email')}:</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                  disabled={adminActionsDisabled}
                />
              </div>
              <div className="form-group">
                <label>
                  {t('users.roleLabel')}
                  <InfoIcon content={t('users.roleInviteHint')} />
                </label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'readonly' | 'write' | 'admin')}
                  required
                  disabled={adminActionsDisabled}
                >
                  <option value="readonly">{t('users.roleOptionReadonly')}</option>
                  <option value="write">{t('users.roleOptionWrite')}</option>
                  <option value="admin">{t('users.roleOptionAdmin')}</option>
                </select>
              </div>
              <div className="form-group">
                <label>
                  {t('users.validForHours')}
                  <InfoIcon content={t('users.validForHoursHint')} />
                </label>
                <input
                  type="number"
                  value={inviteExpiresHours}
                  onChange={(e) => setInviteExpiresHours(parseInt(e.target.value))}
                  min={1}
                  max={720}
                  required
                  disabled={adminActionsDisabled}
                />
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-success" disabled={adminActionsDisabled}>
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
          )}
        </div>
      )}

      {pendingUsers.length > 0 && (
        <div className="users-list-card" style={{ marginBottom: '1.5rem' }}>
          <h3 className="users-section-title">
            {t('users.joinRequests')}
            <InfoIcon content={t('users.joinRequestsInfo')} />
          </h3>
          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>{t('users.name')}</th>
                  <th>{t('users.email')} <InfoIcon content={t('users.emailFromProvider')} /></th>
                  <th>{t('users.provider')}</th>
                  <th>{t('users.createdAt')}</th>
                  {isAdmin && <th>{t('users.actions')}</th>}
                </tr>
              </thead>
              <tbody>
                {pendingUsers.map((u) => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.email || '–'}</td>
                    <td>{t(providerCellKey(u))}</td>
                    <td>{new Date(u.created_at).toLocaleString(getFormatLocale())}</td>
                    {isAdmin && (
                      <td>
                        <div className="user-actions">
                          <button onClick={() => handleOpenApproveModal(u)} className="btn-icon" title={t('users.approve')} disabled={adminActionsDisabled}><MdCheck /></button>
                          <button onClick={() => handleRejectUser(u.id)} className="btn-icon btn-danger" title={t('users.reject')} disabled={adminActionsDisabled}><MdCancel /></button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="users-list-card">
        <h3 className="users-section-title">
          {t('users.activeUsers')}
          <InfoIcon content={t('users.activeUsersInfo')} />
        </h3>
        {isLoading ? (
          <div className="loading-state">{t('users.loading')}</div>
        ) : activeUsers.length > 0 ? (
          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>{t('users.name')}</th>
                  <th>{t('users.email')} <InfoIcon content={t('users.emailFromProvider')} /></th>
                  <th>{t('users.accounts')}</th>
                  <th>{t('users.role')}</th>
                  <th>{t('users.status')}</th>
                  <th>{t('users.createdAt')}</th>
                  {isAdmin && <th>{t('users.actions')}</th>}
                </tr>
              </thead>
              <tbody>
                {activeUsers.map((user) => (
                  <tr key={user.id} className={user.blocked ? 'blocked' : ''}>
                    <td>
                      {user.github_login ? (
                        <a
                          href={`https://github.com/${user.github_login}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="github-user-link"
                          title={t('users.githubTitle', { login: user.github_login })}
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
                      <div className="account-badges">
                        {linkedProviderKeys(user).length > 0 ? (
                          linkedProviderKeys(user).map((p) => (
                            <span
                              key={p}
                              className="badge badge-account"
                              title={t('users.accountLinked', {
                                provider: p === 'github' ? t('users.providerGitHub') : t('users.providerGoogle'),
                              })}
                            >
                              {p === 'github' ? t('users.providerGitHub') : t('users.providerGoogle')}
                            </span>
                          ))
                        ) : (
                          <span className="account-none">–</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <Tooltip content={
                        normalizeRole(user.role) === 'admin' ? t('users.roleTooltipAdmin') :
                        normalizeRole(user.role) === 'write' ? t('users.roleTooltipWrite') :
                        t('users.roleTooltipReadonly')
                      }>
                        <span className={`badge badge-${normalizeRole(user.role) === 'admin' ? 'admin' : normalizeRole(user.role) === 'write' ? 'write' : 'readonly'}`}>
                          {normalizeRole(user.role) === 'admin' ? t('users.roleDisplayAdmin') : normalizeRole(user.role) === 'write' ? t('users.roleDisplayWrite') : t('users.roleDisplayReadonly')}
                        </span>
                      </Tooltip>
                    </td>
                    <td>
                      <Tooltip content={user.blocked ? t('users.statusTooltipBlocked') : t('users.statusTooltipActive')}>
                        {user.blocked ? (
                          <span className="badge badge-error">{t('users.badgeBlocked')}</span>
                        ) : (
                          <span className="badge badge-success">{t('users.badgeActive')}</span>
                        )}
                      </Tooltip>
                    </td>
                    <td>{new Date(user.created_at).toLocaleDateString(getFormatLocale())}</td>
                    {isAdmin && (
                      <td>
                        <div className="user-actions">
                          <button
                            onClick={() => handleEditUser(user)}
                            className="btn-icon"
                            title={t('users.edit')}
                            disabled={adminActionsDisabled}
                          >
                            <MdEdit />
                          </button>
                          {user.blocked ? (
                            <button
                              onClick={() => handleUnblockUser(user.id)}
                              className="btn-icon"
                              title={t('users.unblock')}
                              disabled={adminActionsDisabled}
                            >
                              <MdBlock />
                            </button>
                          ) : (
                            <button
                              onClick={() => handleBlockUser(user.id)}
                              className="btn-icon"
                              title={t('users.block')}
                              disabled={adminActionsDisabled}
                            >
                              <MdBlock />
                            </button>
                          )}
                          <button
                            onClick={() => handleDeleteUser(user.id)}
                            className="btn-icon btn-danger"
                            title={t('common.delete')}
                            disabled={adminActionsDisabled}
                          >
                            <MdDelete />
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">{t('users.noActiveUsers')}</div>
        )}
      </div>

      <div className="users-list-card" style={{ marginTop: '1.5rem' }}>
        <h3>{t('users.invitationsHeading')}</h3>
        {invites.length === 0 ? (
          <div className="empty-state">{t('users.noInvites')}</div>
        ) : (
          <div className="users-table-container">
            <table className="users-table">
              <thead>
                <tr>
                  <th>{t('users.email')}</th>
                  <th>{t('users.role')}</th>
                  <th>{t('users.createdAt')}</th>
                  <th>{t('users.expires')}</th>
                  <th>{t('users.status')}</th>
                  {isAdmin && <th>{t('users.actions')}</th>}
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.id}>
                    <td>{i.recipient_email}</td>
                    <td><span className={`badge badge-${normalizeRole(i.role)}`}>{normalizeRole(i.role) === 'admin' ? t('users.roleDisplayAdmin') : normalizeRole(i.role) === 'write' ? t('users.roleDisplayWrite') : t('users.roleDisplayReadonly')}</span></td>
                    <td>{new Date(i.created_at).toLocaleString(getFormatLocale())}</td>
                    <td>{new Date(i.expires_at).toLocaleString(getFormatLocale())}</td>
                    <td>{i.is_used ? <span className="badge badge-success">{t('users.inviteStatusRedeemed')}</span> : <span className="badge">{t('users.inviteStatusOpen')}</span>}</td>
                    {isAdmin && (
                      <td>
                        {!i.is_used && new Date(i.expires_at) > new Date() && (
                          <button
                            onClick={() => deleteInviteMutation.mutate(i.id)}
                            className="btn-icon btn-danger"
                            title={t('users.revoke')}
                            disabled={adminActionsDisabled}
                          >
                            <MdDelete />
                          </button>
                        )}
                      </td>
                    )}
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
