package lanminecraft.hideandhunt.mixin;

import de.hideandhunt.client.host.Hosting;
import org.spongepowered.asm.mixin.Mixin;

@Mixin(value = Hosting.class, remap = false)
abstract class HostingMixin {
}
