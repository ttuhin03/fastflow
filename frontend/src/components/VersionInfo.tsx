
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { FaExclamationCircle } from 'react-icons/fa';

interface VersionInfoData {
    version: string;
    latest_version?: string;
    update_available: boolean;
    last_checked?: string;
}


const VersionInfo: React.FC = () => {
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

    return (
        <span className="inline-flex items-center gap-1" style={{ fontSize: 'inherit' }}>
            <span className="font-mono">v{displayVersion}</span>
            {!isLoading && isUpdateAvailable && (
                <a
                    href="https://github.com/ttuhin03/fastflow/releases"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-amber-500 hover:text-amber-400"
                    title={`Update available: ${latestVersion}`}
                >
                    <FaExclamationCircle style={{ fontSize: '8px' }} />
                </a>
            )}
        </span>
    );
};

export default VersionInfo;
