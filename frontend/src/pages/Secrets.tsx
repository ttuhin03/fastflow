import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import './Secrets.css'

interface Secret {
  key: string
  value: string
  is_parameter?: boolean
  created_at: string
  updated_at: string
}

export default function Secrets() {
  const queryClient = useQueryClient()
  const [isAdding, setIsAdding] = useState(false)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [formKey, setFormKey] = useState('')
  const [formValue, setFormValue] = useState('')
  const [isParameter, setIsParameter] = useState(false)
  const [showValues, setShowValues] = useState<Record<string, boolean>>({})

  const { data: secrets, isLoading } = useQuery<Secret[]>({
    queryKey: ['secrets'],
    queryFn: async () => {
      const response = await apiClient.get('/secrets')
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (data: { key: string; value: string; is_parameter: boolean }) => {
      const response = await apiClient.post('/secrets', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
      setIsAdding(false)
      setFormKey('')
      setFormValue('')
      setIsParameter(false)
    },
    onError: (error: any) => {
      alert(`Fehler beim Erstellen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: async ({ key, value, isParameter }: { key: string; value: string; isParameter?: boolean }) => {
      const response = await apiClient.put(`/secrets/${key}`, { value, is_parameter: isParameter })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
      setEditingKey(null)
      setFormKey('')
      setFormValue('')
      setIsParameter(false)
    },
    onError: (error: any) => {
      alert(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (key: string) => {
      await apiClient.delete(`/secrets/${key}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['secrets'] })
    },
    onError: (error: any) => {
      alert(`Fehler beim Löschen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formKey || !formValue) {
      alert('Bitte füllen Sie alle Felder aus')
      return
    }

    if (editingKey) {
      updateMutation.mutate({ key: formKey, value: formValue, isParameter: isParameter })
    } else {
      createMutation.mutate({ key: formKey, value: formValue, is_parameter: isParameter })
    }
  }

  const handleEdit = (secret: Secret) => {
    setEditingKey(secret.key)
    setFormKey(secret.key)
    setFormValue(secret.value)
    setIsParameter(secret.is_parameter || false)
    setIsAdding(true)
  }

  const handleDelete = (key: string) => {
    if (confirm(`Möchten Sie das Secret '${key}' wirklich löschen?`)) {
      deleteMutation.mutate(key)
    }
  }

  const toggleShowValue = (key: string) => {
    setShowValues((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="secrets">
      <div className="secrets-header">
        <h2>Secrets & Parameter</h2>
        <button
          onClick={() => {
            setIsAdding(true)
            setEditingKey(null)
            setFormKey('')
            setFormValue('')
            setIsParameter(false)
          }}
          className="add-button"
        >
          + Neues Secret/Parameter
        </button>
      </div>

      {isAdding && (
        <div className="secret-form">
          <h3>{editingKey ? 'Secret bearbeiten' : 'Neues Secret/Parameter'}</h3>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="secret-key">Key:</label>
              <input
                id="secret-key"
                type="text"
                value={formKey}
                onChange={(e) => setFormKey(e.target.value)}
                disabled={!!editingKey}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="secret-value">Value:</label>
              <textarea
                id="secret-value"
                value={formValue}
                onChange={(e) => setFormValue(e.target.value)}
                rows={3}
                required
              />
            </div>
            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={isParameter}
                  onChange={(e) => setIsParameter(e.target.checked)}
                />
                Als Parameter (nicht verschlüsselt)
              </label>
            </div>
            <div className="form-actions">
              <button type="submit" className="submit-button">
                {editingKey ? 'Aktualisieren' : 'Erstellen'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsAdding(false)
                  setEditingKey(null)
                  setFormKey('')
                  setFormValue('')
                  setIsParameter(false)
                }}
                className="cancel-button"
              >
                Abbrechen
              </button>
            </div>
          </form>
        </div>
      )}

      {secrets && secrets.length > 0 ? (
        <table className="secrets-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Type</th>
              <th>Value</th>
              <th>Erstellt</th>
              <th>Aktualisiert</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {secrets.map((secret) => (
              <tr key={secret.key}>
                <td>{secret.key}</td>
                <td>
                  <span className={`type-badge ${secret.is_parameter ? 'parameter' : 'secret'}`}>
                    {secret.is_parameter ? 'Parameter' : 'Secret'}
                  </span>
                </td>
                <td>
                  <div className="value-cell">
                    {showValues[secret.key] ? (
                      <span className="secret-value">{secret.value}</span>
                    ) : (
                      <span className="secret-value-hidden">••••••••</span>
                    )}
                    <button
                      onClick={() => toggleShowValue(secret.key)}
                      className="toggle-button"
                    >
                      {showValues[secret.key] ? 'Verbergen' : 'Anzeigen'}
                    </button>
                  </div>
                </td>
                <td>{new Date(secret.created_at).toLocaleString('de-DE')}</td>
                <td>{new Date(secret.updated_at).toLocaleString('de-DE')}</td>
                <td>
                  <div className="action-buttons">
                    <button
                      onClick={() => handleEdit(secret)}
                      className="edit-button"
                    >
                      Bearbeiten
                    </button>
                    <button
                      onClick={() => handleDelete(secret.key)}
                      className="delete-button"
                    >
                      Löschen
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="no-secrets">Keine Secrets gefunden</p>
      )}
    </div>
  )
}
