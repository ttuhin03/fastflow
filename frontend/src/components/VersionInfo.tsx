import React from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { FaExclamationCircle } from 'react-icons/fa';
import './VersionInfo.css';

interface VersionInfoData {
    version: string;
    latest_version?: string;
    update_available: boolean;
    last_checked?: string;
}

const RELEASES_URL = 'https://github.com/ttuhin03/fastflow/releases';

type VersionInfoVariant = 'footer' | 'banner';

interface VersionInfoProps {
    variant?: VersionInfoVariant;
}

const VersionInfo: React.FC<VersionInfoProps> = ({ variant = 'footer' }) => {
    const { t } = useTranslation();
    const { data, isLoading } = useQuery({
        queryKey: ['system-version'],
        queryFn: async () => {
            const res = await axios.get<VersionInfoData>('/api/system/version');
            return res.data;
        },
        staleTime: 1000 * 60 * 60, // 1 hour
        refetchOnWindowFocus: false,
    });

    const displayVersion = __APP_VERSION__;
    const isUpdateAvailable = data?.update_available;
    const latestVersion = data?.latest_version;

    if (variant === 'banner') {
        if (isLoading || !isUpdateAvailable) return null;
        return (
            <div className="version-update-banner" role="alert">
                <FaExclamationCircle className="version-update-banner-icon" aria-hidden />
                <span className="version-update-banner-text">
                    {t('versionInfo.newVersionAvailable', { version: latestVersion })}
                </span>
                <a
                    href={RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="version-update-banner-link"
                >
                    {t('versionInfo.viewReleases')}
                </a>
            </div>
        );
    }

    return (
        <span className="inline-flex items-center gap-1" style={{ fontSize: 'inherit' }}>
            <span className="font-mono">v{displayVersion}</span>
            {!isLoading && isUpdateAvailable && (
                <a
                    href={RELEASES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-500 hover:text-amber-400"
                    title={t('versionInfo.updateAvailableTitle', { version: latestVersion })}
                >
                    <FaExclamationCircle style={{ fontSize: '8px' }} />
                </a>
            )}
        </span>
    );
};

export default VersionInfo;
