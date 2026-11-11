package lanminecraft.hideandhunt.mixin;

import net.minecraft.server.network.ServerConnectionListener;
import org.spongepowered.asm.mixin.Mixin;

@Mixin(value = ServerConnectionListener.class, remap = false)
abstract class ServerConnectionListenerMixin {
}
