package lanminecraft.hideandhunt;

import java.util.function.BooleanSupplier;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.server.MinecraftServer.MultiplayerScope;

public final class RelayPolicy {
    private static final ThreadLocal<Boolean> OPT_IN = new ThreadLocal<>();

    private RelayPolicy() {
    }

    public static boolean publish(
        IntegratedServer server, MultiplayerScope scope, boolean allowCommands, int port, boolean relayOptIn
    ) {
        return withOptIn(relayOptIn, () -> server.publishServer(scope, allowCommands, port));
    }

    static boolean withOptIn(boolean relayOptIn, BooleanSupplier publish) {
        boolean previous = Boolean.TRUE.equals(OPT_IN.get());
        setOptIn(relayOptIn);
        try {
            return publish.getAsBoolean();
        } finally {
            setOptIn(previous);
        }
    }

    private static void setOptIn(boolean enabled) {
        if (enabled) {
            OPT_IN.set(Boolean.TRUE);
        } else {
            OPT_IN.remove();
        }
    }

    public static boolean canHost(boolean relayEnabled) {
        return relayEnabled && Boolean.TRUE.equals(OPT_IN.get());
    }
}
